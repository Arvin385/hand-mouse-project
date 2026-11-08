"""Check model resolution without importing MediaPipe or opening hardware."""
import ast
import os
import tempfile
import unittest
from pathlib import Path


class StartupTests(unittest.TestCase):
    def test_model_path_is_independent_of_working_directory(self):
        source = Path(__file__).resolve().parents[1] / "vision" / "src" / "init.py"
        tree = ast.parse(source.read_text())
        assignment = next(
            node for node in tree.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "MODEL_PATH"
                    for target in node.targets)
        )
        code = compile(ast.Module(body=[assignment], type_ignores=[]), str(source), "exec")
        previous = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as directory:
                os.chdir(directory)
                namespace = {"Path": Path, "__file__": str(source)}
                exec(code, namespace)
                model = Path(namespace["MODEL_PATH"])
                self.assertEqual(model, source.with_name("hand_landmarker.task"))
                self.assertTrue(model.is_file())
        finally:
            os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
