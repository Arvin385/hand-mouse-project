/* ==========================================================================
 * voice_service.cpp
 *
 * Background speech-to-text service:
 *   - Captures microphone audio continuously (SDL2)
 *   - Runs Silero VAD to detect speech segments
 *   - Transcribes speech segments with whisper.cpp (GPU if available)
 *   - Writes newline-delimited text to a file descriptor (IPC to Python)
 *
 * Usage:
 *   voice_service \
 *       --model  <path/to/whisper-model.bin> \
 *       --vad    <path/to/silero_vad.onnx> \
 *       --threads <N> \
 *       --gpu \
 *       --fd <write_fd>
 *
 * Environment:
 *   VOICE_SERVICE_LOG_LEVEL  — "info" (default) or "debug"
 *
 * Exit codes:
 *   0  — graceful shutdown (SIGTERM/SIGINT)
 *   1  — startup failure (missing args, model load failure, etc.)
 *   2  — VAD init failure
 *   3  — whisper init failure
 *   4  — audio init failure
 *   5  — transcription error
 * ========================================================================== */

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <chrono>
#include <csignal>
#include <atomic>
#include <mutex>
#include <vector>

// whisper.cpp
extern "C" {
#include "whisper.h"
}

// common library (VAD helpers)
#include "common.h"

// SDL2 audio capture (common-sdl)
#include "common-sdl.h"

// ---------------------------------------------------------------------------
// Globals & config
// ---------------------------------------------------------------------------

static std::atomic<bool> g_running{true};
static std::atomic<bool> g_shutdown{false};

static std::mutex g_log_mutex;

static const char *g_model_path   = nullptr;
static const char *g_vad_model    = nullptr;
static int         g_threads      = 2;
static bool        g_use_gpu      = true;
static const char *g_language     = "auto";
static int         g_out_fd       = -1;
static FILE       *g_out_fp       = nullptr;

enum class LogLevel { INFO, DEBUG };
static LogLevel g_log_level = LogLevel::INFO;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

static void log_msg(LogLevel level, const char *fmt, ...) {
    if (level < g_log_level) return;

    const char *prefix = (level == LogLevel::DEBUG) ? "[DBG]" : "[INFO]";

    std::lock_guard<std::mutex> lock(g_log_mutex);

    fprintf(stderr, "%s ", prefix);
    va_list va;
    va_start(va, fmt);
    vfprintf(stderr, fmt, va);
    va_end(va);
    fprintf(stderr, "\n");
    fflush(stderr);
}

static void handle_signal(int sig) {
    if (!g_shutdown.exchange(true)) {
        log_msg(LogLevel::INFO, "Received signal %d — shutting down...", sig);
        g_running = false;
    }
}

// ---------------------------------------------------------------------------
// Argument parsing
// ---------------------------------------------------------------------------

struct Args {
    int argc;
    char **argv;
};

static Args parse_args(int argc, char **argv) {
    Args args{argc, argv};
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        if (arg == "--model"  && i + 1 < argc) { g_model_path = argv[++i]; }
        else if (arg == "--vad"   && i + 1 < argc) { g_vad_model    = argv[++i]; }
        else if (arg == "--threads" && i + 1 < argc) { g_threads = std::atoi(argv[++i]); }
        else if (arg == "--gpu")     { g_use_gpu = true; }
        else if (arg == "--no-gpu")  { g_use_gpu = false; }
        else if (arg == "--lang"  && i + 1 < argc) { g_language = argv[++i]; }
        else if (arg == "--fd"    && i + 1 < argc) { g_out_fd = std::atoi(argv[++i]); }
        else if (arg == "--log")   && i + 1 < argc) {
            std::string level = argv[++i];
            g_log_level = (level == "debug") ? LogLevel::DEBUG : LogLevel::INFO;
        }
        else if (arg == "--help" || arg == "-h") {
            fprintf(stderr,
                "Usage: voice_service [OPTIONS]\n"
                "  --model <path>       Whisper model (.bin)\n"
                "  --vad <path>         Silero VAD model (.onnx)\n"
                "  --threads <N>        Number of threads (default: 2)\n"
                "  --gpu                Enable GPU (CUDA)\n"
                "  --no-gpu             Disable GPU\n"
                "  --lang <code>        Language (default: auto)\n"
                "  --fd <fd>            Write-end FD for IPC output\n"
                "  --log <level>        Log level: info (default), debug\n"
                "  --help, -h           Show this help\n");
            std::exit(0);
        }
    }
    return args;
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

static void init_logging() {
    const char *env = getenv("VOICE_SERVICE_LOG_LEVEL");
    if (env && std::string(env) == "debug") {
        g_log_level = LogLevel::DEBUG;
    }
    log_msg(LogLevel::INFO, "Voice service starting...");
    log_msg(LogLevel::INFO, "Log level: %s",
            g_log_level == LogLevel::DEBUG ? "debug" : "info");
    log_msg(LogLevel::INFO, "Language: %s", g_language);
    log_msg(LogLevel::INFO, "Threads: %d", g_threads);
    log_msg(LogLevel::INFO, "GPU: %s", g_use_gpu ? "yes" : "no");
}

static FILE *init_output_fd() {
    /*
     * Priority for output destination:
     *   1. --fd <N>      — explicit file descriptor
     *   2. stdout (fd 1) — used by Python pipe (default when no --fd)
     *   3. stderr         — logging only
     */
    if (g_out_fd >= 0) {
        log_msg(LogLevel::INFO, "Writing output to fd %d", g_out_fd);
        FILE *fp = fdopen(g_out_fd, "w");
        if (!fp) {
            log_msg(LogLevel::INFO, "fdopen(fd=%d) failed: %s", g_out_fd, strerror(errno));
            return nullptr;
        }
        return fp;
    }

    /* Fallback: write to stdout (fd 1) — used by Python pipe */
    log_msg(LogLevel::INFO, "Writing output to stdout (pipe).");
    return stdout;
}

static void write_output(const char *text) {
    if (!text || !*text) return;
    if (g_out_fp) {
        fprintf(g_out_fp, "%s\n", text);
        fflush(g_out_fp);
    }
    log_msg(LogLevel::INFO, "OUTPUT: %s", text);
}

// ---------------------------------------------------------------------------
// Whisper context
// ---------------------------------------------------------------------------

static whisper_context *init_whisper() {
    if (!g_model_path) {
        fprintf(stderr, "ERROR: --model is required\n");
        return nullptr;
    }

    log_msg(LogLevel::INFO, "Loading whisper model: %s", g_model_path);

    whisper_context_params wparams = whisper_context_default_params();
    if (g_use_gpu) {
        wparams.compute_type = WHISPER_COMPUTE_TYPE_GPU_BIAS;
        log_msg(LogLevel::INFO, "Using GPU (CUDA)");
    }

    whisper_context *ctx = whisper_init_from_file_with_params(g_model_path, wparams);
    if (!ctx) {
        fprintf(stderr, "ERROR: failed to load whisper model from '%s'\n", g_model_path);
        return nullptr;
    }

    const int n_vocab       = whisper_vocab_n(ctx);
    const int n_audio_ctx   = whisper_ctx_n_audio_ctx(ctx);
    const int n_audio_state = whisper_ctx_n_audio_state(ctx);
    const int n_audio_batch = whisper_ctx_n_audio_batch(ctx);
    const int n_text_ctx    = whisper_ctx_n_text_ctx(ctx);
    const int n_threads     = whisper_ctx_n_threads(ctx);
    const float f0          = whisper_ctx_get_ft0(ctx);

    log_msg(LogLevel::INFO, "Whisper model loaded successfully");
    log_msg(LogLevel::DEBUG, "  vocab: %d, audio_ctx: %d, audio_state: %d, "
            "audio_batch: %d, text_ctx: %d, threads: %d, ft0: %.1f",
            n_vocab, n_audio_ctx, n_audio_state, n_audio_batch,
            n_text_ctx, n_threads, f0);

    return ctx;
}

// ---------------------------------------------------------------------------
// VAD context (Silero)
// ---------------------------------------------------------------------------

static whisper_vad_context *init_vad() {
    if (!g_vad_model) {
        log_msg(LogLevel::DEBUG, "No --vad model specified — skipping VAD.");
        return nullptr;
    }

    log_msg(LogLevel::INFO, "Loading Silero VAD model: %s", g_vad_model);

    whisper_vad_params vap = whisper_vad_default_params(WHISPER_VAD_FLAGS_ALL);
    whisper_vad_context *vctx = whisper_vad_init_from_file_with_params(
        g_vad_model, vap);

    if (!vctx) {
        log_msg(LogLevel::INFO, "ERROR: failed to load VAD model from '%s'",
                g_vad_model);
        return nullptr;
    }

    log_msg(LogLevel::INFO, "Silero VAD model loaded successfully");
    return vctx;
}

// ---------------------------------------------------------------------------
// Audio capture
// ---------------------------------------------------------------------------

static audio_async *init_audio() {
    log_msg(LogLevel::INFO, "Initializing audio capture (microphone)...");

    audio_init(NULL, -1, 1, WHISPER_SAMPLE_RATE);

    // Circular buffer length: 30 seconds (enough for streaming)
    const int audio_buffer_ms = 30000;
    audio_async audio(audio_buffer_ms);

    if (!audio.get_device()) {
        log_msg(LogLevel::INFO, "ERROR: failed to find audio capture device");
        audio_finalize();
        return nullptr;
    }

    log_msg(LogLevel::INFO, "Audio capture device: %s", audio.get_device());
    log_msg(LogLevel::INFO, "Audio format: %d channels, %d Hz",
            audio.get_channels(), audio.get_sample_rate());

    return audio.release();  // transfer ownership to caller
}

// ---------------------------------------------------------------------------
// Transcribe a single audio segment
// ---------------------------------------------------------------------------

static std::string transcribe(
        whisper_context *ctx,
        whisper_vad_context *vctx,
        std::vector<float> &pcm,
        audio_async &audio,
        int segment_length_ms) {

    if (pcm.empty()) return "";

    log_msg(LogLevel::DEBUG, "Transcribing %d samples (%.1fs)...",
            (int)pcm.size(), pcm.size() / (float)WHISPER_SAMPLE_RATE);

    // Prepare whisper parameters
    whisper_full_params wparams = whisper_full_default_params(
        WHISPER_SAMPLING_GREEDY);

    wparams.print_progress   = false;
    wparams.print_special    = false;
    wparams.print_realtime   = false;
    wparams.print_timestamps = false;
    wparams.single_segment   = true;
    wparams.max_tokens       = 0;
    wparams.n_threads         = g_threads;
    wparams.language          = g_language;

    // Disable fallback temperatures for faster response
    wparams.temperature_inc  = 0.0f;

    // Whisper context size — auto-detect if possible
    // whisper_ctx_n_audio_ctx(ctx) gives the max context size
    // For short segments, we don't need the full context
    const int audio_ctx = whisper_ctx_n_audio_ctx(ctx);
    wparams.audio_ctx = audio_ctx;

    // Run VAD to get the actual speech region (if VAD model is loaded)
    if (vctx) {
        // The VAD model processes the audio and marks speech/non-speech regions
        // We pass the entire segment to VAD; it will tell us which parts are speech
        if (whisper_vad_detect_speech(vctx, pcm.data(), pcm.size(), WHISPER_SAMPLE_RATE)) {
            log_msg(LogLevel::DEBUG, "VAD detected speech in segment");
        } else {
            log_msg(LogLevel::DEBUG, "VAD: no speech detected — skipping transcription");
            return "";
        }
    }

    // Run whisper full inference
    if (whisper_full(ctx, wparams, pcm.data(), pcm.size()) != 0) {
        log_msg(LogLevel::INFO, "ERROR: whisper_full() failed");
        return "";
    }

    // Extract text from the segment
    const int n_segments = whisper_full_n_segments(ctx);
    if (n_segments <= 0) {
        log_msg(LogLevel::DEBUG, "No transcription segments");
        return "";
    }

    std::string result;
    for (int i = 0; i < n_segments; i++) {
        const char *text = whisper_full_get_segment_text(ctx, i);
        if (text) {
            result += text;
            if (i < n_segments - 1) result += " ";
        }
    }

    // Trim whitespace
    size_t start = result.find_first_not_of(" \t\n\r");
    size_t end   = result.find_last_not_of(" \t\n\r");
    if (start == std::string::npos) return "";
    result = result.substr(start, end - start + 1);

    return result;
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------

static int main_loop(
        whisper_context *ctx,
        whisper_vad_context *vctx,
        audio_async *audio_ptr) {

    if (!ctx || !audio_ptr) {
        log_msg(LogLevel::INFO, "ERROR: whisper context or audio not initialized");
        return 5;
    }

    log_msg(LogLevel::INFO, "Starting main loop (VAD=%s, GPU=%s)...",
            vctx ? "Silero" : "none", g_use_gpu ? "yes" : "no");

    // Audio capture loop parameters
    const int vad_check_ms    = 1000;  // Check VAD every 1s of audio
    const int segment_ms      = 2000;  // Transcribe 2s when speech detected
    const int sleep_ms        = 100;   // Sleep between VAD checks
    const int last_ms         = 1000;  // VAD: compare against last 1s

    int64_t t_last = 0;

    while (g_running.load()) {
        // Get a 1-second audio chunk for VAD checking
        // audio.get() fills a std::vector<float> directly (float32, 16-bit -> float)
        std::vector<float> pcmf32;
        if (!audio_ptr->get(vad_check_ms, pcmf32)) {
            log_msg(LogLevel::DEBUG, "Audio capture stalled");
            std::this_thread::sleep_for(std::chrono::milliseconds(sleep_ms));
            continue;
        }

        // Check timing
        const auto t_now = std::chrono::high_resolution_clock::now();
        const auto t_diff = std::chrono::duration_cast<std::chrono::milliseconds>(
            t_now - t_last).count();

        if (t_diff < vad_check_ms) {
            std::this_thread::sleep_for(std::chrono::milliseconds(sleep_ms));
            continue;
        }

        // Get a longer audio segment for transcription
        std::vector<float> pcmf32_segment;
        audio_ptr->get(segment_ms, pcmf32_segment);

        // VAD detection on the segment
        bool speech_detected = false;

        if (vctx) {
            // Silero VAD
            if (whisper_vad_detect_speech(vctx,
                    pcmf32_segment.data(), pcmf32_segment.size(),
                    WHISPER_SAMPLE_RATE)) {
                speech_detected = true;
            }
        } else {
            // Fallback: energy-based VAD
            speech_detected = vad_simple(
                pcmf32_segment, WHISPER_SAMPLE_RATE, last_ms,
                0.3f, 0.0f, false);
        }

        if (speech_detected) {
            t_last = std::chrono::time_point_cast<std::chrono::milliseconds>(t_now).count();

            // Transcribe the segment
            std::string text = transcribe(ctx, vctx, pcmf32_segment, *audio_ptr, segment_ms);

            if (!text.empty()) {
                write_output(text.c_str());
            }
        } else {
            std::this_thread::sleep_for(std::chrono::milliseconds(sleep_ms));
        }
    }

    log_msg(LogLevel::INFO, "Main loop exited.");
    return 0;
}

// ---------------------------------------------------------------------------
// Entry point
// ---------------------------------------------------------------------------

int main(int argc, char **argv) {
    parse_args(argc, argv);

    init_logging();
    init_output_fd();

    // Set up signal handlers for graceful shutdown
    signal(SIGTERM, handle_signal);
    signal(SIGINT,  handle_signal);

    // Initialize whisper
    whisper_context *ctx = init_whisper();
    if (!ctx) {
        log_msg(LogLevel::INFO, "FATAL: whisper init failed");
        return 3;
    }

    // Initialize VAD (optional)
    whisper_vad_context *vctx = init_vad();
    if (!vctx && g_vad_model) {
        log_msg(LogLevel::INFO, "FATAL: VAD init failed");
        whisper_free(ctx);
        return 2;
    }

    // Initialize audio capture
    audio_async *audio_ptr = init_audio();
    if (!audio_ptr) {
        log_msg(LogLevel::INFO, "FATAL: audio init failed");
        if (vctx) whisper_vad_free(vctx);
        whisper_free(ctx);
        return 4;
    }

    // Run main loop
    int result = main_loop(ctx, vctx, audio_ptr);

    // Cleanup
    audio_ptr->restore();
    audio_finalize();
    delete audio_ptr;
    if (vctx) whisper_vad_free(vctx);
    whisper_free(ctx);

    if (g_out_fp) fclose(g_out_fp);

    log_msg(LogLevel::INFO, "Voice service stopped (exit code %d)", result);
    return result;
}
