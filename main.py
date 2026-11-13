from __future__ import annotations

import base64
from collections.abc import Callable
import ctypes
from datetime import datetime
import json
import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox
from typing import TypedDict
import winreg

# Configuração de log para diagnóstico seguro sem engolir erros silenciosamente
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ServiceGuard")

# Constantes gerais
INTERVALO_CHECAGEM_MS = 5 * 60 * 1000
SLOTS_MINIMOS = 5
SLOTS_MAXIMOS = 12
ALTURA_ESTIMADA_CARD = 76
CREATE_NO_WINDOW = 0x08000000
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
TITULO_JANELA = (
    "ServiceGuard • Controle de Serviços do Windows — Desenvolvido por Kleberson Cordeiro"
)
ATRASO_TAREFA_BOOT = "PT20S"  # aguarda 20s após o logon para o sistema estabilizar
REG_RUN_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_APP_NAME = "ControleServicosWindows"
TASK_SCH_NAME = "ControleServicosWindowsBoot"
ARQUIVO_SELECIONADOS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "servicos_selecionados.json"
)

# Paleta Visual (Obsidian & Cyber Indigo Dashboard)
CORES: dict[str, str] = {
    "bg_janela": "#090d16",
    "bg_topbar": "#111827",
    "bg_card": "#131c2e",
    "bg_kpi": "#111827",
    "bg_kpi_ativo": "#1e1b4b",
    "bg_input": "#111827",
    "borda_card": "#1e293b",
    "linha_topo_accent": "#6366f1",
    "texto_primario": "#f8fafc",
    "texto_secundario": "#94a3b8",
    "texto_muted": "#64748b",
    "tag_bg": "#1e293b",
    "tag_txt": "#cbd5e1",
    "esmeralda": "#10b981",
    "esmeralda_hover": "#059669",
    "esmeralda_bg": "#064e3b",
    "esmeralda_txt": "#34d399",
    "coral": "#f43f5e",
    "coral_hover": "#e11d48",
    "coral_bg": "#4c0519",
    "coral_txt": "#fb7185",
    "ciano_txt": "#22d3ee",
    "indigo": "#6366f1",
    "indigo_hover": "#4f46e5",
    "ouro": "#f59e0b",
    "ouro_bg": "#451a03",
    "ouro_txt": "#fbbf24",
    "neutro": "#1e293b",
    "neutro_hover": "#334155",
}


class ServicoInfo(TypedDict):
    name: str
    display: str
    status: str
    start_type: str


class KpiRefs(TypedDict):
    borda: tk.Frame
    card: tk.Frame
    lbl_titulo: tk.Label
    lbl_valor: tk.Label
    cor_destaque: str


class SlotCardRefs(TypedDict):
    borda: tk.Frame
    faixa_status: tk.Frame
    lbl_display: tk.Label
    lbl_tag_nome: tk.Label
    badge_status: tk.Label
    badge_boot: tk.Label
    btn_boot: tk.Button
    btn_iniciar: tk.Button
    btn_parar: tk.Button


# ==================== FUNÇÕES UTILITÁRIAS DE SISTEMA (WINDOWS) ====================
def ativar_high_dpi() -> None:
    """Ativa nitidez em telas Full HD / 4K (High DPI)."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except OSError as exc:
        logger.debug("Não foi possível definir DPI awareness: %s", exc)


def is_admin() -> bool:
    """Verifica se o processo atual possui privilégios de Administrador."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def escapar_ps(texto: str) -> str:
    """Escapa aspas simples para uso seguro dentro de strings literais do PowerShell."""
    return str(texto).replace("'", "''")


def obter_executavel_e_script() -> tuple[str, str]:
    """
    Retorna (exe_path, script_path) priorizando o pythonw.exe do interpretador BASE
    (sys.base_prefix), e não o da pasta .venv — assim o auto-start continua
    funcionando mesmo se a .venv for apagada ou recriada.
    """
    script_path = os.path.abspath(__file__)
    candidatos = [
        os.path.join(sys.base_prefix, "pythonw.exe"),
        os.path.join(os.path.dirname(sys.executable), "pythonw.exe"),
    ]
    for candidato in candidatos:
        if os.path.exists(candidato):
            return candidato, script_path
    return sys.executable, script_path


def verificar_app_no_boot() -> bool:
    """Verifica se a Tarefa Agendada elevada (RunLevel Highest) está registrada no Windows."""
    try:
        res = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_SCH_NAME],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
        )
        return res.returncode == 0
    except OSError as exc:
        logger.warning("Falha ao consultar a Tarefa Agendada: %s", exc)
        return False


def remover_autostart_legado_registro() -> None:
    """
    Remove a entrada antiga em HKCU\\...\\Run (versões anteriores do app), evitando que
    o Windows abra uma segunda instância sem privilégios junto com a Tarefa Agendada.
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, REG_RUN_PATH, 0, winreg.KEY_SET_VALUE
        ) as chave:
            winreg.DeleteValue(chave, REG_APP_NAME)
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Falha ao remover auto-start legado do Registro: %s", exc)


def trazer_instancia_existente_para_frente() -> bool:
    """
    Verifica se já existe uma janela visível do ServiceGuard na área de trabalho atual.
    Se encontrar, restaura e traz para frente, retornando True.
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, TITULO_JANELA)
        if hwnd and user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetForegroundWindow(hwnd)
            return True
    except OSError as exc:
        logger.debug("Não foi possível focar a instância existente: %s", exc)
    return False


def ler_start_type_registro(nome_servico: str, fallback: str = "Manual") -> str:
    """Lê o tipo de inicialização do serviço diretamente do Registro do Windows."""
    mapa = {2: "Automatic", 3: "Manual", 4: "Disabled"}
    try:
        caminho = f"SYSTEM\\CurrentControlSet\\Services\\{nome_servico}"
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, caminho, 0, winreg.KEY_READ
        ) as chave:
            valor, _ = winreg.QueryValueEx(chave, "Start")
            return mapa.get(int(valor), fallback)
    except OSError:
        return (
            fallback if fallback in ("Automatic", "Manual", "Disabled") else "Manual"
        )


def consultar_status_unico(nome_servico: str) -> str | None:
    """Consulta rapidamente o status atual (Running/Stopped) de um único serviço via sc.exe."""
    res = subprocess.run(
        ["sc.exe", "query", nome_servico],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    saida = res.stdout.upper()
    if "RUNNING" in saida:
        return "Running"
    if "STOPPED" in saida:
        return "Stopped"
    if "START_PENDING" in saida:
        return "StartPending"
    if "STOP_PENDING" in saida:
        return "StopPending"
    return None


def executar_powershell_elevado(ps_cmd: str) -> bool:
    """
    Executa um comando PowerShell codificado em Base64 UTF-16LE (-EncodedCommand).
    Retorna True se o comando teve êxito (código 0) ou False se cancelado/falhou.
    """
    encoded = base64.b64encode(ps_cmd.encode("utf-16-le")).decode("ascii")
    if is_admin():
        cmd = ["powershell", "-NoProfile", "-EncodedCommand", encoded]
    else:
        comando_runas = (
            "try { "
            "$p = Start-Process powershell -Verb RunAs -WindowStyle Hidden -Wait -PassThru "
            f"-ArgumentList '-NoProfile -EncodedCommand {encoded}'; "
            "exit $p.ExitCode "
            "} catch { exit 1 }"
        )
        cmd = ["powershell", "-NoProfile", "-Command", comando_runas]
    res = subprocess.run(
        cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW
    )
    return res.returncode == 0


def criar_botao(
    parent: tk.Misc,
    texto: str,
    bg: str,
    bg_hover: str,
    fg: str,
    comando: Callable[[], None],
    width: int | None = None,
    pady: int = 5,
    padx: int = 10,
    font_size: int = 9,
) -> tk.Button:
    """Cria um botão estilizado com efeito hover suave."""
    btn = tk.Button(
        parent,
        text=texto,
        bg=bg,
        fg=fg,
        activebackground=bg_hover,
        activeforeground=fg,
        font=("Segoe UI", font_size, "bold"),
        relief="flat",
        bd=0,
        cursor="hand2",
        padx=padx,
        pady=pady,
        command=comando,
    )
    if width is not None:
        btn.config(width=width)
    btn._bg_normal = bg  # type: ignore[attr-defined]
    btn._bg_hover = bg_hover  # type: ignore[attr-defined]
    btn.bind(
        "<Enter>",
        lambda _e: btn.config(bg=getattr(btn, "_bg_hover", bg_hover))
        if str(btn["state"]) != "disabled"
        else None,
    )
    btn.bind(
        "<Leave>",
        lambda _e: btn.config(bg=getattr(btn, "_bg_normal", bg))
        if str(btn["state"]) != "disabled"
        else None,
    )
    return btn


# ==================== CLASSE PRINCIPAL DA APLICAÇÃO (POO) ====================
class ServiceGuardApp:
    """Gerenciador visual de serviços do Windows com inicialização forçada no boot."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.encerrado: bool = False
        self.timer_checagem: str | None = None
        self.todos_servicos: list[ServicoInfo] = []
        self.servicos_filtrados: list[ServicoInfo] = []
        self.servicos_selecionados: set[str] = set()
        self.filtro_atual: str = "all"
        self.scroll_offset: int = 0
        self.num_slots_visiveis: int = SLOTS_MINIMOS
        self.operacao_em_andamento: bool = False
        self.verificacao_boot_realizada: bool = False

        self.kpis_widgets: dict[str, KpiRefs] = {}
        self.slots_cards: list[SlotCardRefs] = []

        self.carregar_servicos_selecionados()
        if self.servicos_selecionados:
            self.filtro_atual = "selecionados"

        self._configurar_janela()
        self._construir_interface()
        self.atualizar_interface()

    def _configurar_janela(self) -> None:
        self.root.title(TITULO_JANELA)
        largura_janela = 980
        altura_janela = 710
        pos_x = (self.root.winfo_screenwidth() // 2) - (largura_janela // 2)
        pos_y = (self.root.winfo_screenheight() // 2) - (altura_janela // 2)
        self.root.geometry(f"{largura_janela}x{altura_janela}+{pos_x}+{pos_y}")
        self.root.minsize(920, 620)
        self.root.configure(bg=CORES["bg_janela"])
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self.ao_fechar_janela)

    def _agendar_ui(self, callback: Callable[[], None]) -> None:
        """Executa um callback na thread da UI somente se a janela ainda estiver ativa."""
        if self.encerrado:
            return
        try:
            self.root.after(0, lambda: callback() if not self.encerrado else None)
        except tk.TclError:
            pass

    def ao_fechar_janela(self) -> None:
        """Cancela timers pendentes e encerra a janela de forma limpa sem TclError."""
        self.encerrado = True
        if self.timer_checagem is not None:
            try:
                self.root.after_cancel(self.timer_checagem)
            except tk.TclError:
                pass
            self.timer_checagem = None
        self.root.destroy()

    # -------------------- Persistência JSON --------------------
    def carregar_servicos_selecionados(self) -> None:
        """Carrega do arquivo JSON a lista de serviços selecionados pelo usuário no app."""
        if os.path.exists(ARQUIVO_SELECIONADOS):
            try:
                with open(ARQUIVO_SELECIONADOS, "r", encoding="utf-8") as arq:
                    dados = json.load(arq)
                    if isinstance(dados, list):
                        self.servicos_selecionados = {
                            str(item).strip().lower()
                            for item in dados
                            if str(item).strip()
                        }
                        return
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Erro ao ler %s: %s", ARQUIVO_SELECIONADOS, exc)
        self.servicos_selecionados = set()

    def salvar_servicos_selecionados(self) -> None:
        """Salva no arquivo JSON os serviços selecionados pelo usuário no app."""
        try:
            map_nomes = {s["name"].lower(): s["name"] for s in self.todos_servicos}
            lista_salvar = sorted(
                [map_nomes.get(n, n) for n in self.servicos_selecionados]
            )
            with open(ARQUIVO_SELECIONADOS, "w", encoding="utf-8") as arq:
                json.dump(lista_salvar, arq, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.error("Erro ao salvar %s: %s", ARQUIVO_SELECIONADOS, exc)
            messagebox.showwarning(
                "Aviso ao salvar seleção",
                f"Não foi possível salvar a lista de serviços selecionados em disco:\n{exc}",
            )

    # -------------------- Auto-Start do Próprio App --------------------
    def alternar_app_no_boot(self) -> None:
        """
        Habilita ou desabilita a inicialização deste aplicativo junto com o Windows
        exclusivamente via Tarefa Agendada com privilégios elevados (RunLevel Highest).
        Assim o app já abre como Administrador no logon e força os serviços SEM pedir UAC.
        """
        if self.operacao_em_andamento:
            return
        ativar = not verificar_app_no_boot()
        exe_usar, script_path = obter_executavel_e_script()
        usuario = f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"

        if ativar:
            ps_cmd = (
                f"$act = New-ScheduledTaskAction -Execute '{escapar_ps(exe_usar)}' "
                f"-Argument '\"{escapar_ps(script_path)}\" --boot' "
                f"-WorkingDirectory '{escapar_ps(os.path.dirname(script_path))}'; "
                f"$trig = New-ScheduledTaskTrigger -AtLogOn -User '{escapar_ps(usuario)}'; "
                f"$trig.Delay = '{ATRASO_TAREFA_BOOT}'; "
                f"$prin = New-ScheduledTaskPrincipal -UserId '{escapar_ps(usuario)}' "
                "-LogonType Interactive -RunLevel Highest; "
                "$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
                "-DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) "
                "-MultipleInstances IgnoreNew; "
                f"Register-ScheduledTask -TaskName '{TASK_SCH_NAME}' -Action $act "
                "-Trigger $trig -Principal $prin -Settings $set -Force -ErrorAction Stop | Out-Null"
            )
        else:
            ps_cmd = (
                f"Unregister-ScheduledTask -TaskName '{TASK_SCH_NAME}' "
                "-Confirm:$false -ErrorAction Stop"
            )

        self.operacao_em_andamento = True
        self.atualizar_estado_interacao()
        self.btn_app_boot.config(state="disabled")
        self.lbl_rodape.config(
            text="⏳ Configurando Tarefa Agendada no Windows (confirme o UAC)...",
            fg=CORES["ouro_txt"],
        )

        def tarefa() -> None:
            executar_powershell_elevado(ps_cmd)
            remover_autostart_legado_registro()
            ativo_agora = verificar_app_no_boot()

            def concluir() -> None:
                self.operacao_em_andamento = False
                self.btn_app_boot.config(state="normal")
                self.atualizar_estado_interacao()
                self.atualizar_botao_app_boot()
                if ativo_agora == ativar:
                    if ativar:
                        self.lbl_rodape.config(
                            text="✔ App configurado para iniciar com o Windows como Administrador (sem UAC no boot)!",
                            fg=CORES["esmeralda_txt"],
                        )
                    else:
                        self.lbl_rodape.config(
                            text="✔ Este aplicativo NÃO iniciará mais automaticamente com o Windows.",
                            fg=CORES["ouro_txt"],
                        )
                else:
                    self.lbl_rodape.config(
                        text="⚠ Configuração de inicialização não alterada (UAC cancelado ou sem permissão).",
                        fg=CORES["coral_txt"],
                    )

            self._agendar_ui(concluir)

        threading.Thread(target=tarefa, daemon=True).start()

    def atualizar_botao_app_boot(self) -> None:
        """Atualiza o visual do botão de auto-start do próprio aplicativo no topo."""
        if verificar_app_no_boot():
            self.btn_app_boot._bg_normal = CORES["esmeralda_bg"]  # type: ignore[attr-defined]
            self.btn_app_boot._bg_hover = CORES["esmeralda"]  # type: ignore[attr-defined]
            self.btn_app_boot.config(
                text="🟢 Iniciar com o Windows: ATIVADO",
                bg=CORES["esmeralda_bg"],
                fg=CORES["esmeralda_txt"],
            )
        else:
            self.btn_app_boot._bg_normal = CORES["neutro"]  # type: ignore[attr-defined]
            self.btn_app_boot._bg_hover = CORES["indigo"]  # type: ignore[attr-defined]
            self.btn_app_boot.config(
                text="⚪ Iniciar com o Windows: DESATIVADO",
                bg=CORES["neutro"],
                fg=CORES["texto_secundario"],
            )

    # -------------------- Consulta e Controle de Serviços --------------------
    def obter_todos_servicos(self) -> list[ServicoInfo]:
        """Consulta todos os serviços do Windows, seu status e seu tipo de inicialização."""
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
                "Get-Service -ErrorAction SilentlyContinue | "
                "Select-Object Name, DisplayName, "
                "@{N='StatusStr';E={\"$($_.Status)\"}}, "
                "@{N='StartTypeStr';E={\"$($_.StartType)\"}} | "
                "ConvertTo-Json -Compress"
            ),
        ]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
        lista_final: list[ServicoInfo] = []
        saida = res.stdout.strip()
        if saida:
            try:
                parsed = json.loads(saida)
                if isinstance(parsed, dict):
                    parsed = [parsed]
                for item in parsed:
                    nome = str(item.get("Name") or "")
                    if not nome:
                        continue
                    display = str(item.get("DisplayName") or nome)
                    status = str(item.get("StatusStr") or "Unknown")
                    fallback_st = str(item.get("StartTypeStr") or "Manual")
                    start_type = ler_start_type_registro(nome, fallback=fallback_st)
                    lista_final.append(
                        {
                            "name": nome,
                            "display": display,
                            "status": status,
                            "start_type": start_type,
                        }
                    )
            except json.JSONDecodeError as exc:
                logger.warning("Falha ao decodificar JSON de serviços: %s", exc)

        lista_final.sort(
            key=lambda s: (
                0 if s["name"].lower() in self.servicos_selecionados else 1,
                0 if s["status"] == "Running" else 1,
                s["display"].lower(),
            )
        )
        return lista_final

    def alternar_selecao_servico_boot(self, nome_servico: str) -> None:
        """
        Adiciona ou remove o serviço da aba exclusiva 'INICIAR PELO APP'.
        Quando adicionado, também configura o serviço como Automático e força sua inicialização.
        """
        if self.operacao_em_andamento:
            return

        chave = nome_servico.lower()
        if chave in self.servicos_selecionados:
            self.servicos_selecionados.discard(chave)
            self.salvar_servicos_selecionados()
            self.aplicar_filtros(resetar_scroll=False)
            self.lbl_rodape.config(
                text=f"✔ '{nome_servico}' removido da aba 'INICIAR PELO APP'.",
                fg=CORES["ouro_txt"],
            )
            return

        self.servicos_selecionados.add(chave)
        self.salvar_servicos_selecionados()
        self.aplicar_filtros(resetar_scroll=False)
        self.lbl_rodape.config(
            text=f"⭐ '{nome_servico}' adicionado à aba 'INICIAR PELO APP'! Forçando inicialização e configurando boot...",
            fg=CORES["ouro_txt"],
        )

        self.operacao_em_andamento = True
        self.atualizar_estado_interacao()

        def tarefa_add() -> None:
            nome_seguro = escapar_ps(nome_servico)
            ps_cmd = (
                f"Set-Service -Name '{nome_seguro}' -StartupType Automatic -ErrorAction SilentlyContinue; "
                f"Start-Service -Name '{nome_seguro}' -ErrorAction SilentlyContinue"
            )
            sucesso_uac = executar_powershell_elevado(ps_cmd)
            novo_st = ler_start_type_registro(nome_servico)
            novo_status = consultar_status_unico(nome_servico)

            def concluir_add() -> None:
                self.operacao_em_andamento = False
                for srv in self.todos_servicos:
                    if srv["name"].lower() == chave:
                        srv["start_type"] = novo_st
                        if novo_status:
                            srv["status"] = novo_status
                        break
                self.aplicar_filtros(resetar_scroll=False)
                if sucesso_uac:
                    self.lbl_rodape.config(
                        text=f"✔ '{nome_servico}' salvo na aba 'INICIAR PELO APP' (iniciará automaticamente com o App)!",
                        fg=CORES["esmeralda_txt"],
                    )
                else:
                    self.lbl_rodape.config(
                        text=f"⭐ '{nome_servico}' salvo na aba 'INICIAR PELO APP' (UAC cancelado para início imediato).",
                        fg=CORES["ouro_txt"],
                    )

            self._agendar_ui(concluir_add)

        threading.Thread(target=tarefa_add, daemon=True).start()

    def controlar_servico(
        self, nome_servico: str, acao: str, start_type_atual: str = "Manual"
    ) -> None:
        """Inicia ou para um serviço do Windows."""
        if self.operacao_em_andamento:
            return
        self.operacao_em_andamento = True
        self.atualizar_estado_interacao()

        acao_txt = "Iniciando" if acao == "Start" else "Parando"
        self.lbl_rodape.config(
            text=f"⏳ {acao_txt} serviço '{nome_servico}' (confirme o UAC se solicitado)...",
            fg=CORES["ouro_txt"],
        )

        def tarefa() -> None:
            nome_seguro = escapar_ps(nome_servico)
            comandos: list[str] = []
            if acao == "Start" and start_type_atual == "Disabled":
                comandos.append(
                    f"Set-Service -Name '{nome_seguro}' -StartupType Manual -ErrorAction SilentlyContinue"
                )
            force_flag = " -Force" if acao == "Stop" else ""
            comandos.append(
                f"{acao}-Service -Name '{nome_seguro}'{force_flag} -ErrorAction SilentlyContinue"
            )
            sucesso_uac = executar_powershell_elevado("; ".join(comandos))

            novo_status = consultar_status_unico(nome_servico)
            novo_start_type = ler_start_type_registro(nome_servico)

            def concluir() -> None:
                self.operacao_em_andamento = False
                esperado = "Running" if acao == "Start" else "Stopped"
                for srv in self.todos_servicos:
                    if srv["name"].lower() == nome_servico.lower():
                        if novo_status:
                            srv["status"] = novo_status
                        srv["start_type"] = novo_start_type
                        break
                self.aplicar_filtros(resetar_scroll=False)
                if not sucesso_uac:
                    self.lbl_rodape.config(
                        text=f"⚠ Permissão de Administrador (UAC) cancelada ao alterar '{nome_servico}'.",
                        fg=CORES["coral_txt"],
                    )
                elif novo_status == esperado:
                    verbo = "iniciado" if acao == "Start" else "parado"
                    self.lbl_rodape.config(
                        text=f"✔ Serviço '{nome_servico}' {verbo} com sucesso!",
                        fg=CORES["esmeralda_txt"],
                    )
                else:
                    self.lbl_rodape.config(
                        text=f"⚠ O serviço '{nome_servico}' não mudou para {esperado} (status atual: {novo_status or 'Desconhecido'}).",
                        fg=CORES["coral_txt"],
                    )

            self._agendar_ui(concluir)

        threading.Thread(target=tarefa, daemon=True).start()

    def forcar_acao_selecionados(
        self, acao: str, automatico_no_boot: bool = False
    ) -> None:
        """
        Força automaticamente a inicialização (ou parada) de TODOS os serviços definidos
        na aba 'INICIAR PELO APP' assim que o aplicativo inicia com o sistema (ou sob demanda).
        """
        if self.operacao_em_andamento:
            return

        map_nomes = {s["name"].lower(): s["name"] for s in self.todos_servicos}
        alvos = [
            map_nomes.get(chave, chave) for chave in sorted(self.servicos_selecionados)
        ]

        if not alvos:
            if not automatico_no_boot:
                messagebox.showinfo(
                    "Nenhum serviço na lista",
                    "Você ainda não adicionou nenhum serviço à aba '⭐ INICIAR PELO APP'.\n\n"
                    "Vá em 'TODOS OS SERVIÇOS' ou 'EM EXECUÇÃO' e clique em '⭐ + Iniciar pelo App' nos serviços desejados.",
                )
            return

        if acao == "Start" and automatico_no_boot and "--boot" not in sys.argv:
            precisam_acao = [
                s["name"]
                for s in self.todos_servicos
                if s["name"].lower() in self.servicos_selecionados
                and (s["status"] != "Running" or s["start_type"] != "Automatic")
            ]
            if not precisam_acao:
                self.lbl_rodape.config(
                    text=f"✔ Inicialização automática verificada: todos os {len(alvos)} serviço(s) selecionados já estão ativos!",
                    fg=CORES["esmeralda_txt"],
                )
                return
            alvos = precisam_acao

        self.operacao_em_andamento = True
        self.atualizar_estado_interacao()
        acao_txt = "Inicializando automaticamente" if acao == "Start" else "Parando"
        self.lbl_rodape.config(
            text=f"🚀 {acao_txt} {len(alvos)} serviço(s) selecionado(s) pelo App ({', '.join(alvos[:4])})...",
            fg=CORES["ouro_txt"],
        )

        def tarefa() -> None:
            comandos: list[str] = []
            force_flag = " -Force" if acao == "Stop" else ""
            for nome in alvos:
                nome_seguro = escapar_ps(nome)
                if acao == "Start":
                    comandos.append(
                        f"Set-Service -Name '{nome_seguro}' -StartupType Automatic -ErrorAction SilentlyContinue"
                    )
                comandos.append(
                    f"{acao}-Service -Name '{nome_seguro}'{force_flag} -ErrorAction SilentlyContinue"
                )
            sucesso_uac = executar_powershell_elevado("; ".join(comandos))
            self._agendar_ui(
                lambda: self.finalizar_lote_e_atualizar(
                    len(alvos), acao, sucesso_uac
                )
            )

        threading.Thread(target=tarefa, daemon=True).start()

    def finalizar_lote_e_atualizar(
        self, qtd: int = 0, acao: str = "Start", sucesso_uac: bool = True
    ) -> None:
        self.operacao_em_andamento = False
        if not sucesso_uac:
            self.atualizar_estado_interacao()
            self.lbl_rodape.config(
                text="⚠ Operação em lote cancelada pelo usuário no UAC.",
                fg=CORES["coral_txt"],
            )
            return
        self.atualizar_interface(
            manter_scroll=True,
            msg_personalizada=(
                f"🚀 Inicialização forçada concluída: {qtd} serviço(s) selecionado(s) iniciados com o App!"
                if acao == "Start"
                else f"✔ {qtd} serviço(s) selecionado(s) parados."
            ),
        )

    # -------------------- Filtros, Renderização e Rolagem --------------------
    def atualizar_estado_interacao(self) -> None:
        estado = "disabled" if self.operacao_em_andamento else "normal"
        self.btn_atualizar.config(state=estado)
        self.btn_lote_iniciar.config(state=estado)
        self.btn_lote_parar.config(state=estado)
        for slot in self.slots_cards:
            slot["btn_boot"].config(state=estado)
            slot["btn_iniciar"].config(state=estado)
            slot["btn_parar"].config(state=estado)

    def aplicar_filtros(self, resetar_scroll: bool = False) -> None:
        """Atualiza os KPIs do painel e filtra os serviços conforme aba e busca."""
        termo = self.var_busca.get().strip().lower()
        qtd_sel = sum(
            1
            for s in self.todos_servicos
            if s["name"].lower() in self.servicos_selecionados
        )
        qtd_all = len(self.todos_servicos)
        qtd_running = sum(1 for s in self.todos_servicos if s["status"] == "Running")
        qtd_stopped = qtd_all - qtd_running

        self.kpis_widgets["selecionados"]["lbl_valor"].config(text=str(qtd_sel))
        self.kpis_widgets["all"]["lbl_valor"].config(text=str(qtd_all))
        self.kpis_widgets["running"]["lbl_valor"].config(text=str(qtd_running))
        self.kpis_widgets["stopped"]["lbl_valor"].config(text=str(qtd_stopped))

        for chave, item in self.kpis_widgets.items():
            ativo = self.filtro_atual == chave
            borda_cor = item["cor_destaque"] if ativo else CORES["borda_card"]
            bg_cor = CORES["bg_kpi_ativo"] if ativo else CORES["bg_kpi"]
            item["borda"].config(bg=borda_cor)
            item["card"].config(bg=bg_cor)
            item["lbl_titulo"].config(
                bg=bg_cor, fg="#ffffff" if ativo else CORES["texto_secundario"]
            )
            item["lbl_valor"].config(bg=bg_cor)

        if self.filtro_atual == "selecionados":
            self.barra_lote_selecionados.pack(
                fill="x", padx=24, pady=(4, 0), before=self.area_lista
            )
        else:
            self.barra_lote_selecionados.pack_forget()

        resultado: list[ServicoInfo] = []
        for srv in self.todos_servicos:
            if (
                self.filtro_atual == "selecionados"
                and srv["name"].lower() not in self.servicos_selecionados
            ):
                continue
            if self.filtro_atual == "running" and srv["status"] != "Running":
                continue
            if self.filtro_atual == "stopped" and srv["status"] == "Running":
                continue
            if termo and (
                termo not in srv["name"].lower()
                and termo not in srv["display"].lower()
            ):
                continue
            resultado.append(srv)

        self.servicos_filtrados = resultado
        self.lbl_contador_busca.config(text=f"{len(self.servicos_filtrados)} exibidos")

        if resetar_scroll:
            self.scroll_offset = 0
        else:
            max_offset = max(
                0, len(self.servicos_filtrados) - self.num_slots_visiveis
            )
            self.scroll_offset = max(0, min(self.scroll_offset, max_offset))

        self.renderizar_slots()

    def selecionar_filtro(self, novo_filtro: str) -> None:
        self.filtro_atual = novo_filtro
        self.aplicar_filtros(resetar_scroll=True)

    def _ao_redimensionar_lista(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        """Ajusta dinamicamente quantos cartões cabem quando a janela é maximizada ou redimensionada."""
        if event.height < 100:
            return
        altura_card = ALTURA_ESTIMADA_CARD
        if self.slots_cards:
            h_real = self.slots_cards[0]["borda"].winfo_height()
            if h_real > 30:
                altura_card = h_real + 10
        calculado = max(
            SLOTS_MINIMOS,
            min(SLOTS_MAXIMOS, event.height // altura_card),
        )
        if calculado != self.num_slots_visiveis:
            self.num_slots_visiveis = calculado
            max_offset = max(
                0, len(self.servicos_filtrados) - self.num_slots_visiveis
            )
            self.scroll_offset = max(0, min(self.scroll_offset, max_offset))
            self.renderizar_slots()

    def atualizar_scrollbar_custom(self) -> None:
        """Desenha a barra de rolagem escura personalizada e a oculta quando não é necessária."""
        total = len(self.servicos_filtrados)
        if total <= self.num_slots_visiveis:
            if self.scrollbar_canvas.winfo_ismapped():
                self.scrollbar_canvas.pack_forget()
            return

        if not self.scrollbar_canvas.winfo_ismapped():
            self.scrollbar_canvas.pack(side="right", fill="y", padx=(10, 0), pady=5)

        self.scrollbar_canvas.update_idletasks()
        altura = max(self.scrollbar_canvas.winfo_height(), 200)
        inicio_frac = self.scroll_offset / total
        fim_frac = min(1.0, (self.scroll_offset + self.num_slots_visiveis) / total)

        y1 = int(inicio_frac * altura)
        y2 = max(y1 + 28, int(fim_frac * altura))
        if y2 > altura:
            y2 = altura
            y1 = max(0, altura - 28)

        self.scrollbar_canvas.delete("thumb")
        self.scrollbar_canvas.create_rectangle(
            2,
            y1,
            8,
            y2,
            fill=CORES["indigo"],
            outline="",
            tags="thumb",
        )

    def ao_clicar_ou_arrastar_scrollbar(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        total = len(self.servicos_filtrados)
        if total <= self.num_slots_visiveis:
            return
        altura = max(self.scrollbar_canvas.winfo_height(), 1)
        frac = max(0.0, min(1.0, event.y / altura))
        max_offset = max(0, total - self.num_slots_visiveis)
        self.scroll_offset = int(round(frac * max_offset))
        self.renderizar_slots()

    def renderizar_slots(self) -> None:
        """Renderiza os cartões visíveis na viewport."""
        total = len(self.servicos_filtrados)
        self.atualizar_scrollbar_custom()

        for i in range(SLOTS_MAXIMOS):
            slot = self.slots_cards[i]
            if i >= self.num_slots_visiveis:
                slot["borda"].pack_forget()
                continue

            idx = self.scroll_offset + i
            if idx >= total:
                slot["borda"].pack_forget()
                continue

            srv = self.servicos_filtrados[idx]
            chave = srv["name"].lower()
            escolhido_no_app = chave in self.servicos_selecionados

            slot["borda"].config(
                bg=CORES["ouro"] if escolhido_no_app else CORES["borda_card"]
            )
            slot["borda"].pack(fill="x", pady=5)

            descricao = srv["display"]
            if len(descricao) > 48:
                descricao = descricao[:45] + "..."
            slot["lbl_display"].config(text=descricao)

            nome_tec = srv["name"]
            if len(nome_tec) > 28:
                nome_tec = nome_tec[:25] + "..."
            slot["lbl_tag_nome"].config(text=f" {nome_tec} ")

            status = srv["status"]
            if status == "Running":
                slot["faixa_status"].config(bg=CORES["esmeralda"])
                slot["badge_status"].config(
                    text="● STATUS: ATIVO",
                    bg=CORES["esmeralda_bg"],
                    fg=CORES["esmeralda_txt"],
                )
            elif status == "Stopped":
                slot["faixa_status"].config(bg=CORES["coral"])
                slot["badge_status"].config(
                    text="○ STATUS: PARADO",
                    bg=CORES["coral_bg"],
                    fg=CORES["coral_txt"],
                )
            else:
                slot["faixa_status"].config(bg=CORES["ouro_txt"])
                slot["badge_status"].config(
                    text=f"● STATUS: {status.upper()}",
                    bg=CORES["ouro_bg"],
                    fg=CORES["ouro_txt"],
                )

            slot["btn_iniciar"].config(
                command=lambda n=srv["name"], st=srv["start_type"]: self.controlar_servico(
                    n, "Start", st
                ),
            )
            slot["btn_parar"].config(
                command=lambda n=srv["name"], st=srv["start_type"]: self.controlar_servico(
                    n, "Stop", st
                ),
            )

            if escolhido_no_app:
                slot["badge_boot"].config(
                    text="⭐ INICIA JUNTO COM O APP",
                    bg=CORES["ouro_bg"],
                    fg=CORES["ouro_txt"],
                )
                slot["btn_boot"]._bg_normal = CORES["ouro_bg"]  # type: ignore[attr-defined]
                slot["btn_boot"]._bg_hover = CORES["coral"]  # type: ignore[attr-defined]
                slot["btn_boot"].config(
                    text="★ Remover da Aba",
                    bg=CORES["ouro_bg"],
                    fg=CORES["ouro_txt"],
                    command=lambda n=srv["name"]: self.alternar_selecao_servico_boot(n),
                )
            else:
                start_type = srv["start_type"]
                if start_type == "Automatic":
                    slot["badge_boot"].config(
                        text="⚙ WINDOWS: AUTOMÁTICO",
                        bg=CORES["neutro"],
                        fg=CORES["texto_secundario"],
                    )
                elif start_type == "Disabled":
                    slot["badge_boot"].config(
                        text="🚫 WINDOWS: DESATIVADO",
                        bg=CORES["coral_bg"],
                        fg=CORES["coral_txt"],
                    )
                else:
                    slot["badge_boot"].config(
                        text="⚙ WINDOWS: MANUAL",
                        bg=CORES["neutro"],
                        fg=CORES["texto_secundario"],
                    )
                slot["btn_boot"]._bg_normal = CORES["indigo"]  # type: ignore[attr-defined]
                slot["btn_boot"]._bg_hover = CORES["indigo_hover"]  # type: ignore[attr-defined]
                slot["btn_boot"].config(
                    text="⭐ + Iniciar pelo App",
                    bg=CORES["indigo"],
                    fg="#ffffff",
                    command=lambda n=srv["name"]: self.alternar_selecao_servico_boot(n),
                )

        if total == 0:
            if self.filtro_atual == "selecionados":
                self.lbl_vazio.config(
                    text=(
                        "Nenhum serviço foi selecionado no App ainda.\n\n"
                        "Clique na aba '📋 TODOS OS SERVIÇOS' ou '● EM EXECUÇÃO' acima e aperte o botão\n"
                        "'⭐ + Iniciar pelo App' nos serviços que você quer que o App inicie automaticamente!"
                    )
                )
            else:
                self.lbl_vazio.config(
                    text="Nenhum serviço encontrado para o filtro ou pesquisa atual."
                )
            self.lbl_vazio.pack(pady=45)
        else:
            self.lbl_vazio.pack_forget()

        self.atualizar_estado_interacao()

    def rolar_lista(self, passos: int) -> None:
        """Desloca a lista de cartões pelo número de passos informado."""
        max_offset = max(0, len(self.servicos_filtrados) - self.num_slots_visiveis)
        self.scroll_offset = max(0, min(self.scroll_offset + passos, max_offset))
        self.renderizar_slots()

    def ao_rolar_mouse(self, event: tk.Event) -> None:  # type: ignore[type-arg]
        self.rolar_lista(-1 if event.delta > 0 else 1)

    def atualizar_interface(
        self, manter_scroll: bool = False, msg_personalizada: str | None = None
    ) -> None:
        if self.encerrado:
            return
        if self.timer_checagem is not None:
            try:
                self.root.after_cancel(self.timer_checagem)
            except tk.TclError:
                pass
            self.timer_checagem = None

        if self.operacao_em_andamento:
            self.timer_checagem = self.root.after(
                INTERVALO_CHECAGEM_MS,
                lambda: self.atualizar_interface(manter_scroll=True),
            )
            return

        self.btn_atualizar.config(state="disabled")
        if not msg_personalizada:
            self.lbl_rodape.config(
                text="🔄 Sincronizando lista de serviços do Windows...",
                fg=CORES["texto_secundario"],
            )

        def tarefa() -> None:
            lista = self.obter_todos_servicos()

            def aplicar_na_tela() -> None:
                self.todos_servicos = lista
                self.aplicar_filtros(resetar_scroll=not manter_scroll)
                if not self.operacao_em_andamento:
                    self.btn_atualizar.config(state="normal")
                horario = datetime.now().strftime("%H:%M:%S")
                if msg_personalizada:
                    self.lbl_rodape.config(
                        text=msg_personalizada, fg=CORES["esmeralda_txt"]
                    )
                else:
                    self.lbl_rodape.config(
                        text=(
                            f"✔ Sincronizado às {horario} • "
                            f"{len(self.servicos_selecionados)} na aba 'INICIAR PELO APP' • "
                            f"{len(self.servicos_filtrados)} exibidos"
                        ),
                        fg=CORES["texto_secundario"],
                    )
                self.timer_checagem = self.root.after(
                    INTERVALO_CHECAGEM_MS,
                    lambda: self.atualizar_interface(manter_scroll=True),
                )

                if not self.verificacao_boot_realizada:
                    self.verificacao_boot_realizada = True
                    if self.servicos_selecionados:
                        self.forcar_acao_selecionados("Start", automatico_no_boot=True)

            self._agendar_ui(aplicar_na_tela)

        threading.Thread(target=tarefa, daemon=True).start()

    # -------------------- Construção dos Widgets --------------------
    def _construir_interface(self) -> None:
        # Linha superior de destaque (Cyber Indigo Accent)
        tk.Frame(self.root, bg=CORES["linha_topo_accent"], height=3).pack(fill="x")

        # Top Bar (Cabeçalho Escuro Destacado)
        topbar = tk.Frame(self.root, bg=CORES["bg_topbar"], padx=24, pady=14)
        topbar.pack(fill="x")

        col_top_acoes = tk.Frame(topbar, bg=CORES["bg_topbar"])
        col_top_acoes.pack(side="right", padx=(16, 0))

        self.btn_atualizar = criar_botao(
            col_top_acoes,
            "↻ Sincronizar",
            CORES["neutro"],
            CORES["neutro_hover"],
            CORES["texto_primario"],
            lambda: self.atualizar_interface(manter_scroll=True),
            pady=7,
            padx=14,
        )
        self.btn_atualizar.pack(side="right", padx=(8, 0))

        self.btn_app_boot = criar_botao(
            col_top_acoes,
            "⚪ Iniciar com o Windows: ...",
            CORES["neutro"],
            CORES["indigo"],
            CORES["texto_secundario"],
            self.alternar_app_no_boot,
            pady=7,
            padx=14,
        )
        self.btn_app_boot.pack(side="right")
        self.atualizar_botao_app_boot()

        col_titulo = tk.Frame(topbar, bg=CORES["bg_topbar"])
        col_titulo.pack(side="left", fill="x", expand=True)

        linha_titulo_topo = tk.Frame(col_titulo, bg=CORES["bg_topbar"])
        linha_titulo_topo.pack(fill="x", anchor="w")

        tk.Label(
            linha_titulo_topo,
            text="⚡ ServiceGuard Windows",
            font=("Segoe UI", 16, "bold"),
            bg=CORES["bg_topbar"],
            fg=CORES["texto_primario"],
            anchor="w",
        ).pack(side="left")

        tk.Label(
            linha_titulo_topo,
            text="Desenvolvido por Kleberson Cordeiro",
            font=("Segoe UI", 8, "bold"),
            bg=CORES["bg_kpi_ativo"],
            fg=CORES["ciano_txt"],
            padx=8,
            pady=2,
        ).pack(side="left", padx=(10, 0), pady=(3, 0))

        tk.Label(
            col_titulo,
            text="Gerenciamento de serviços e inicialização forçada automática junto com o sistema",
            font=("Segoe UI", 9),
            bg=CORES["bg_topbar"],
            fg=CORES["texto_secundario"],
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # Linha divisória sutil abaixo do Top Bar
        tk.Frame(self.root, bg=CORES["borda_card"], height=1).pack(fill="x")

        # Painel de 4 Abas / KPIs Interativos no Topo
        frame_kpis = tk.Frame(self.root, bg=CORES["bg_janela"], padx=24, pady=12)
        frame_kpis.pack(fill="x")

        definicoes_kpis = [
            (
                "selecionados",
                "⭐ INICIAR PELO APP (MEUS)",
                CORES["ouro"],
                CORES["ouro_txt"],
            ),
            (
                "all",
                "📋 TODOS OS SERVIÇOS",
                CORES["indigo"],
                CORES["texto_primario"],
            ),
            (
                "running",
                "● EM EXECUÇÃO (ATIVOS)",
                CORES["esmeralda"],
                CORES["esmeralda_txt"],
            ),
            (
                "stopped",
                "○ SERVIÇOS PARADOS",
                CORES["coral"],
                CORES["coral_txt"],
            ),
        ]

        for idx_k, (chave_k, titulo_k, cor_borda_k, cor_num_k) in enumerate(
            definicoes_kpis
        ):
            borda_k = tk.Frame(
                frame_kpis, bg=CORES["borda_card"], padx=1, pady=1, cursor="hand2"
            )
            borda_k.pack(
                side="left",
                fill="both",
                expand=True,
                padx=(0 if idx_k == 0 else 8, 0),
            )

            card_k = tk.Frame(
                borda_k, bg=CORES["bg_kpi"], padx=14, pady=8, cursor="hand2"
            )
            card_k.pack(fill="both", expand=True)

            lbl_t = tk.Label(
                card_k,
                text=titulo_k,
                font=("Segoe UI", 8, "bold"),
                bg=CORES["bg_kpi"],
                fg=CORES["texto_secundario"],
                anchor="w",
                cursor="hand2",
            )
            lbl_t.pack(fill="x")

            lbl_v = tk.Label(
                card_k,
                text="0",
                font=("Segoe UI", 16, "bold"),
                bg=CORES["bg_kpi"],
                fg=cor_num_k,
                anchor="w",
                cursor="hand2",
            )
            lbl_v.pack(fill="x", pady=(2, 0))

            for widget in (borda_k, card_k, lbl_t, lbl_v):
                widget.bind(
                    "<Button-1>", lambda _e, c=chave_k: self.selecionar_filtro(c)
                )

            self.kpis_widgets[chave_k] = {
                "borda": borda_k,
                "card": card_k,
                "lbl_titulo": lbl_t,
                "lbl_valor": lbl_v,
                "cor_destaque": cor_borda_k,
            }

        # Barra de Pesquisa Moderna
        barra_busca_ext = tk.Frame(self.root, bg=CORES["bg_janela"], padx=24, pady=2)
        barra_busca_ext.pack(fill="x")

        borda_busca = tk.Frame(barra_busca_ext, bg=CORES["borda_card"], padx=1, pady=1)
        borda_busca.pack(fill="x")

        frame_busca = tk.Frame(borda_busca, bg=CORES["bg_input"], padx=12, pady=7)
        frame_busca.pack(fill="x")

        tk.Label(
            frame_busca,
            text="🔎 Pesquisar serviço:",
            font=("Segoe UI", 9, "bold"),
            bg=CORES["bg_input"],
            fg=CORES["texto_secundario"],
        ).pack(side="left", padx=(0, 8))

        btn_limpar_busca = criar_botao(
            frame_busca,
            "✕ Limpar",
            CORES["neutro"],
            CORES["neutro_hover"],
            CORES["texto_secundario"],
            lambda: self.var_busca.set(""),
            pady=2,
            padx=8,
            font_size=8,
        )
        btn_limpar_busca.pack(side="right", padx=(8, 0))

        self.lbl_contador_busca = tk.Label(
            frame_busca,
            text="0 exibidos",
            font=("Segoe UI", 8),
            bg=CORES["bg_input"],
            fg=CORES["texto_muted"],
        )
        self.lbl_contador_busca.pack(side="right", padx=(8, 0))

        self.var_busca = tk.StringVar()
        self.var_busca.trace_add(
            "write", lambda *_: self.aplicar_filtros(resetar_scroll=True)
        )

        entry_busca = tk.Entry(
            frame_busca,
            textvariable=self.var_busca,
            font=("Segoe UI", 10),
            bg=CORES["bg_input"],
            fg=CORES["texto_primario"],
            insertbackground=CORES["texto_primario"],
            relief="flat",
            bd=0,
        )
        entry_busca.pack(side="left", fill="x", expand=True)

        # Barra de Ações em Lote exclusiva da aba "⭐ INICIAR PELO APP"
        self.barra_lote_selecionados = tk.Frame(self.root, bg=CORES["bg_janela"])
        borda_lote = tk.Frame(
            self.barra_lote_selecionados, bg=CORES["ouro"], padx=1, pady=1
        )
        borda_lote.pack(fill="x")
        interno_lote = tk.Frame(borda_lote, bg=CORES["bg_topbar"], padx=14, pady=6)
        interno_lote.pack(fill="x")

        self.btn_lote_parar = criar_botao(
            interno_lote,
            "■ Parar Todos da Aba",
            CORES["coral"],
            CORES["coral_hover"],
            "#ffffff",
            lambda: self.forcar_acao_selecionados("Stop", automatico_no_boot=False),
            pady=4,
            padx=10,
            font_size=8,
        )
        self.btn_lote_parar.pack(side="right", padx=(6, 0))

        self.btn_lote_iniciar = criar_botao(
            interno_lote,
            "🚀 Forçar Início de Todos Agora",
            CORES["esmeralda"],
            CORES["esmeralda_hover"],
            "#ffffff",
            lambda: self.forcar_acao_selecionados("Start", automatico_no_boot=False),
            pady=4,
            padx=10,
            font_size=8,
        )
        self.btn_lote_iniciar.pack(side="right")

        tk.Label(
            interno_lote,
            text="⭐ O App força automaticamente a inicialização destes serviços ao iniciar com o sistema:",
            font=("Segoe UI", 9, "bold"),
            bg=CORES["bg_topbar"],
            fg=CORES["ouro_txt"],
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

        # Barra de Status Inferior + Assinatura de Desenvolvimento
        rodape = tk.Frame(self.root, bg=CORES["bg_topbar"], padx=24, pady=9)
        rodape.pack(fill="x", side="bottom")
        tk.Frame(self.root, bg=CORES["borda_card"], height=1).pack(
            fill="x", side="bottom"
        )

        borda_assinatura = tk.Frame(rodape, bg=CORES["indigo"], padx=1, pady=1)
        borda_assinatura.pack(side="right", padx=(14, 0))

        tk.Label(
            borda_assinatura,
            text="⚡ Desenvolvido por Kleberson Cordeiro",
            font=("Segoe UI", 8, "bold"),
            bg=CORES["bg_kpi_ativo"],
            fg=CORES["texto_primario"],
            padx=10,
            pady=2,
        ).pack()

        self.lbl_rodape = tk.Label(
            rodape,
            text="Inicializando painel...",
            font=("Segoe UI", 8),
            bg=CORES["bg_topbar"],
            fg=CORES["texto_secundario"],
            anchor="w",
        )
        self.lbl_rodape.pack(side="left", fill="x", expand=True)

        # Container da Lista de Cards + Scrollbar Escura Personalizada
        self.area_lista = tk.Frame(self.root, bg=CORES["bg_janela"], padx=24, pady=6)
        self.area_lista.pack(fill="both", expand=True)

        self.container_cards = tk.Frame(self.area_lista, bg=CORES["bg_janela"])
        self.container_cards.pack(side="left", fill="both", expand=True)
        self.container_cards.bind("<Configure>", self._ao_redimensionar_lista)

        self.scrollbar_canvas = tk.Canvas(
            self.area_lista,
            width=10,
            bg=CORES["bg_topbar"],
            highlightthickness=1,
            highlightbackground=CORES["borda_card"],
            bd=0,
            cursor="hand2",
        )
        self.scrollbar_canvas.bind("<Button-1>", self.ao_clicar_ou_arrastar_scrollbar)
        self.scrollbar_canvas.bind("<B1-Motion>", self.ao_clicar_ou_arrastar_scrollbar)
        self.scrollbar_canvas.bind(
            "<Configure>", lambda _e: self.atualizar_scrollbar_custom()
        )

        self.lbl_vazio = tk.Label(
            self.container_cards,
            text="",
            font=("Segoe UI", 10),
            bg=CORES["bg_janela"],
            fg=CORES["texto_secundario"],
            justify="center",
        )

        for _ in range(SLOTS_MAXIMOS):
            borda = tk.Frame(
                self.container_cards, bg=CORES["borda_card"], padx=1, pady=1
            )

            card_interno = tk.Frame(borda, bg=CORES["bg_card"])
            card_interno.pack(fill="both", expand=True)

            faixa_status = tk.Frame(card_interno, bg=CORES["esmeralda"], width=5)
            faixa_status.pack(side="left", fill="y")

            corpo_card = tk.Frame(card_interno, bg=CORES["bg_card"], padx=14, pady=10)
            corpo_card.pack(side="left", fill="both", expand=True)

            col_btns = tk.Frame(corpo_card, bg=CORES["bg_card"])
            col_btns.pack(side="right", padx=(12, 0))

            btn_parar = criar_botao(
                col_btns,
                "■ Parar",
                CORES["coral"],
                CORES["coral_hover"],
                "#ffffff",
                lambda: None,
                width=8,
                pady=6,
                padx=6,
            )
            btn_parar.pack(side="right", padx=(6, 0))

            btn_iniciar = criar_botao(
                col_btns,
                "▶ Iniciar",
                CORES["esmeralda"],
                CORES["esmeralda_hover"],
                "#ffffff",
                lambda: None,
                width=8,
                pady=6,
                padx=6,
            )
            btn_iniciar.pack(side="right", padx=(6, 0))

            btn_boot = criar_botao(
                col_btns,
                "⭐ + Iniciar pelo App",
                CORES["indigo"],
                CORES["indigo_hover"],
                "#ffffff",
                lambda: None,
                width=19,
                pady=6,
                padx=8,
            )
            btn_boot.pack(side="right")

            col_info = tk.Frame(corpo_card, bg=CORES["bg_card"])
            col_info.pack(side="left", fill="both", expand=True)

            linha_topo = tk.Frame(col_info, bg=CORES["bg_card"])
            linha_topo.pack(fill="x", anchor="w")

            lbl_display = tk.Label(
                linha_topo,
                text="",
                font=("Segoe UI", 10, "bold"),
                bg=CORES["bg_card"],
                fg=CORES["texto_primario"],
            )
            lbl_display.pack(side="left")

            lbl_tag_nome = tk.Label(
                linha_topo,
                text="",
                font=("Consolas", 8, "bold"),
                bg=CORES["tag_bg"],
                fg=CORES["tag_txt"],
                padx=4,
                pady=1,
            )
            lbl_tag_nome.pack(side="left", padx=(8, 0))

            linha_badges = tk.Frame(col_info, bg=CORES["bg_card"])
            linha_badges.pack(fill="x", anchor="w", pady=(5, 0))

            badge_status = tk.Label(
                linha_badges,
                text="",
                font=("Segoe UI", 8, "bold"),
                bg=CORES["esmeralda_bg"],
                fg=CORES["esmeralda_txt"],
                padx=8,
                pady=2,
            )
            badge_status.pack(side="left", padx=(0, 6))

            badge_boot = tk.Label(
                linha_badges,
                text="",
                font=("Segoe UI", 8, "bold"),
                bg=CORES["neutro"],
                fg=CORES["texto_secundario"],
                padx=8,
                pady=2,
            )
            badge_boot.pack(side="left")

            self.slots_cards.append(
                {
                    "borda": borda,
                    "faixa_status": faixa_status,
                    "lbl_display": lbl_display,
                    "lbl_tag_nome": lbl_tag_nome,
                    "badge_status": badge_status,
                    "badge_boot": badge_boot,
                    "btn_boot": btn_boot,
                    "btn_iniciar": btn_iniciar,
                    "btn_parar": btn_parar,
                }
            )

        # Suporte a rolagem com a roda do mouse e teclado
        self.root.bind_all("<MouseWheel>", self.ao_rolar_mouse)
        self.root.bind("<Up>", lambda _e: self.rolar_lista(-1))
        self.root.bind("<Down>", lambda _e: self.rolar_lista(1))
        self.root.bind("<Prior>", lambda _e: self.rolar_lista(-self.num_slots_visiveis))
        self.root.bind("<Next>", lambda _e: self.rolar_lista(self.num_slots_visiveis))

        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(300, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()


def main() -> None:
    """Ponto de entrada principal da aplicação."""
    ativar_high_dpi()
    if trazer_instancia_existente_para_frente():
        sys.exit(0)

    remover_autostart_legado_registro()

    root = tk.Tk()
    _app = ServiceGuardApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
