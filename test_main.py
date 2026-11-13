import os
import unittest
from unittest.mock import MagicMock, patch

import main


class TestServiceGuard(unittest.TestCase):
    def test_escapar_ps(self) -> None:
        self.assertEqual(main.escapar_ps("AnyDesk"), "AnyDesk")
        self.assertEqual(main.escapar_ps("Srv'Teste"), "Srv''Teste")

    def test_obter_executavel_e_script_usa_base_prefix(self) -> None:
        exe, script = main.obter_executavel_e_script()
        self.assertTrue(os.path.exists(exe))
        self.assertTrue(script.endswith("main.py"))
        self.assertNotIn(".venv", exe.lower())

    @patch("main.subprocess.run")
    def test_consultar_status_unico(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="STATE : 4 RUNNING\n")
        self.assertEqual(main.consultar_status_unico("Spooler"), "Running")

        mock_run.return_value = MagicMock(stdout="STATE : 1 STOPPED\n")
        self.assertEqual(main.consultar_status_unico("Spooler"), "Stopped")

    @patch("main.subprocess.run")
    def test_verificar_app_no_boot(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        self.assertTrue(main.verificar_app_no_boot())

        mock_run.return_value = MagicMock(returncode=1)
        self.assertFalse(main.verificar_app_no_boot())


if __name__ == "__main__":
    unittest.main()
