import ctypes
from datetime import datetime
import json
import subprocess
import sys
import threading
import tkinter as tk

# Substitua pelos nomes reais dos serviços
SERVICOS = ["Spooler", "wuauserv"]

# Intervalo de verificação automática em milissegundos (5 minutos = 300.000 ms)
INTERVALO_CHECAGEM_MS = 5 * 60 * 1000
timer_checagem = None

# Ativa nitidez em telas Full HD / 4K (High DPI)
try:
  ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
  pass


def is_admin():
  try:
    return bool(ctypes.windll.shell32.IsUserAnAdmin())
  except Exception:
    return False

# Paleta de cores moderna (Dark Theme)
CORES = {
    "bg_janela": "#0f172a",       # Azul ardósia escuro
    "bg_card": "#1e293b",         # Fundo dos cartões
    "borda_card": "#334155",      # Borda sutil dos cartões
    "texto_primario": "#f8fafc",  # Branco suave
    "texto_secundario": "#94a3b8",# Cinza azulado
    "verde_bg": "#064e3b",        # Fundo badge ativo
    "verde_txt": "#34d399",       # Texto badge ativo
    "vermelho_bg": "#7f1d1d",     # Fundo badge parado
    "vermelho_txt": "#f87171",    # Texto badge parado
    "amarelo_bg": "#78350f",      # Fundo badge carregando/erro
    "amarelo_txt": "#fbbf24",     # Texto badge carregando/erro
    "btn_iniciar": "#10b981",     # Botão verde
    "btn_iniciar_hover": "#059669",
    "btn_parar": "#ef4444",       # Botão vermelho
    "btn_parar_hover": "#dc2626",
    "btn_neutro": "#334155",      # Botão secundário
    "btn_neutro_hover": "#475569",
}


def criar_botao(parent, texto, bg, bg_hover, fg, comando, width=None, pady=6):
  btn = tk.Button(
      parent,
      text=texto,
      bg=bg,
      fg=fg,
      activebackground=bg_hover,
      activeforeground=fg,
      font=("Segoe UI", 9, "bold"),
      relief="flat",
      bd=0,
      cursor="hand2",
      padx=12,
      pady=pady,
      command=comando,
  )
  if width:
    btn.config(width=width)
  btn.bind("<Enter>", lambda e: btn.config(bg=bg_hover))
  btn.bind("<Leave>", lambda e: btn.config(bg=bg))
  return btn


def obter_todos_status():
  lista = ",".join([f"'{n}'" for n in SERVICOS])
  cmd = (
      "powershell -NoProfile -Command \""
      "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
      f"Get-Service -Name {lista} -ErrorAction SilentlyContinue | "
      "Select-Object Name, DisplayName, @{N='StatusStr';E={$_.Status.ToString()}} | "
      "ConvertTo-Json -Compress\""
  )
  res = subprocess.run(
      cmd,
      capture_output=True,
      text=True,
      encoding="utf-8",
      errors="replace",
      shell=True,
      creationflags=0x08000000,
  )
  dados = {}
  saida = res.stdout.strip()
  if saida:
    try:
      parsed = json.loads(saida)
      if isinstance(parsed, dict):
        parsed = [parsed]
      for item in parsed:
        dados[item["Name"].lower()] = {
            "status": item.get("StatusStr", "Erro"),
            "display": item.get("DisplayName", item["Name"]),
        }
    except Exception:
      pass
  return dados


def definir_estado_botoes(estado):
  for btn in botoes_acao:
    btn.config(state=estado)


def controlar_servico(nomes, acao):
  definir_estado_botoes("disabled")
  acao_txt = "Iniciando" if acao == "Start" else "Parando"
  lbl_rodape.config(
      text=f"⏳ {acao_txt}: {', '.join(nomes)}...", fg=CORES["amarelo_txt"]
  )

  def tarefa():
    lista = ",".join([f"'{n}'" for n in nomes])
    force_flag = " -Force" if acao == "Stop" else ""
    ps_cmd = f"{acao}-Service -Name {lista}{force_flag}"
    if is_admin():
      cmd = f'powershell -NoProfile -Command "{ps_cmd}"'
    else:
      cmd = (
          "powershell -NoProfile -Command "
          f'"Start-Process powershell -Verb RunAs -WindowStyle Hidden -Wait '
          f"-ArgumentList '-NoProfile -Command \\\"{ps_cmd}\\\"'\""
      )
    subprocess.run(cmd, shell=True, creationflags=0x08000000)
    app.after(0, atualizar_interface)

  threading.Thread(target=tarefa, daemon=True).start()


def atualizar_interface():
  global timer_checagem
  if timer_checagem is not None:
    app.after_cancel(timer_checagem)
    timer_checagem = None

  definir_estado_botoes("disabled")
  lbl_rodape.config(text="🔄 Consultando status dos serviços...", fg=CORES["texto_secundario"])

  def tarefa():
    dados = obter_todos_status()

    def aplicar_na_tela():
      global timer_checagem
      for srv in SERVICOS:
        info = dados.get(srv.lower())
        ui = cards_servicos[srv]

        if info:
          status = info["status"]
          ui["subtitulo"].config(text=info["display"])
        else:
          status = "Não encontrado"
          ui["subtitulo"].config(text="Serviço não localizado no Windows")

        if status == "Running":
          ui["badge"].config(
              text="● ATIVO",
              bg=CORES["verde_bg"],
              fg=CORES["verde_txt"],
          )
        elif status == "Stopped":
          ui["badge"].config(
              text="● PARADO",
              bg=CORES["vermelho_bg"],
              fg=CORES["vermelho_txt"],
          )
        else:
          ui["badge"].config(
              text=f"● {status.upper()}",
              bg=CORES["amarelo_bg"],
              fg=CORES["amarelo_txt"],
          )

      definir_estado_botoes("normal")
      horario = datetime.now().strftime("%H:%M:%S")
      lbl_rodape.config(
          text=f"✔ Atualizado às {horario} • Checagem automática a cada 5 min",
          fg=CORES["texto_secundario"],
      )
      timer_checagem = app.after(INTERVALO_CHECAGEM_MS, atualizar_interface)

    app.after(0, aplicar_na_tela)

  threading.Thread(target=tarefa, daemon=True).start()


# Configuração da Janela Principal
app = tk.Tk()
app.title("Gerenciador de Serviços")
altura_janela = 240 + (len(SERVICOS) * 85)
largura_janela = 480
pos_x = (app.winfo_screenwidth() // 2) - (largura_janela // 2)
pos_y = (app.winfo_screenheight() // 2) - (altura_janela // 2)
app.geometry(f"{largura_janela}x{altura_janela}+{pos_x}+{pos_y}")
app.configure(bg=CORES["bg_janela"])
app.resizable(False, False)

cards_servicos = {}
botoes_acao = []

# Cabeçalho
header = tk.Frame(app, bg=CORES["bg_janela"], padx=24, pady=18)
header.pack(fill="x")

tk.Label(
    header,
    text="Controle de Serviços",
    font=("Segoe UI", 15, "bold"),
    bg=CORES["bg_janela"],
    fg=CORES["texto_primario"],
    anchor="w",
).pack(fill="x")

tk.Label(
    header,
    text="Gerencie rapidamente o estado dos serviços do Windows",
    font=("Segoe UI", 9),
    bg=CORES["bg_janela"],
    fg=CORES["texto_secundario"],
    anchor="w",
).pack(fill="x", pady=(2, 0))

# Container dos Cards de Serviços
container_cards = tk.Frame(app, bg=CORES["bg_janela"], padx=24)
container_cards.pack(fill="both", expand=True)

for srv in SERVICOS:
  # Borda externa do Card
  borda = tk.Frame(container_cards, bg=CORES["borda_card"], padx=1, pady=1)
  borda.pack(fill="x", pady=6)

  card = tk.Frame(borda, bg=CORES["bg_card"], padx=14, pady=12)
  card.pack(fill="both")

  # Coluna Esquerda: Nome Técnico + Nome Amigável
  col_info = tk.Frame(card, bg=CORES["bg_card"])
  col_info.pack(side="left", fill="both", expand=True)

  linha_topo = tk.Frame(col_info, bg=CORES["bg_card"])
  linha_topo.pack(fill="x", anchor="w")

  tk.Label(
      linha_topo,
      text=srv,
      font=("Segoe UI", 11, "bold"),
      bg=CORES["bg_card"],
      fg=CORES["texto_primario"],
  ).pack(side="left")

  badge = tk.Label(
      linha_topo,
      text="● ...",
      font=("Segoe UI", 8, "bold"),
      bg=CORES["amarelo_bg"],
      fg=CORES["amarelo_txt"],
      padx=8,
      pady=2,
  )
  badge.pack(side="left", padx=10)

  lbl_sub = tk.Label(
      col_info,
      text="Carregando descrição...",
      font=("Segoe UI", 8),
      bg=CORES["bg_card"],
      fg=CORES["texto_secundario"],
      anchor="w",
  )
  lbl_sub.pack(fill="x", pady=(3, 0))

  # Coluna Direita: Botões Individuais
  col_btns = tk.Frame(card, bg=CORES["bg_card"])
  col_btns.pack(side="right")

  btn_stop = criar_botao(
      col_btns,
      "Parar",
      CORES["btn_parar"],
      CORES["btn_parar_hover"],
      "#ffffff",
      lambda s=srv: controlar_servico([s], "Stop"),
      pady=5,
  )
  btn_stop.pack(side="right", padx=(6, 0))

  btn_start = criar_botao(
      col_btns,
      "Iniciar",
      CORES["btn_iniciar"],
      CORES["btn_iniciar_hover"],
      "#ffffff",
      lambda s=srv: controlar_servico([s], "Start"),
      pady=5,
  )
  btn_start.pack(side="right")

  botoes_acao.extend([btn_start, btn_stop])
  cards_servicos[srv] = {"badge": badge, "subtitulo": lbl_sub}

# Barra de Ações Globais
frame_acoes = tk.Frame(app, bg=CORES["bg_janela"], padx=24, pady=12)
frame_acoes.pack(fill="x")

btn_iniciar_todos = criar_botao(
    frame_acoes,
    "▶ Iniciar Todos",
    CORES["btn_iniciar"],
    CORES["btn_iniciar_hover"],
    "#ffffff",
    lambda: controlar_servico(SERVICOS, "Start"),
    pady=8,
)
btn_iniciar_todos.pack(side="left", fill="x", expand=True, padx=(0, 6))

btn_parar_todos = criar_botao(
    frame_acoes,
    "■ Parar Todos",
    CORES["btn_parar"],
    CORES["btn_parar_hover"],
    "#ffffff",
    lambda: controlar_servico(SERVICOS, "Stop"),
    pady=8,
)
btn_parar_todos.pack(side="left", fill="x", expand=True, padx=6)

btn_atualizar = criar_botao(
    frame_acoes,
    "↻ Atualizar",
    CORES["btn_neutro"],
    CORES["btn_neutro_hover"],
    CORES["texto_primario"],
    atualizar_interface,
    pady=8,
)
btn_atualizar.pack(side="right", padx=(6, 0))

botoes_acao.extend([btn_iniciar_todos, btn_parar_todos, btn_atualizar])

# Rodapé de Status
rodape = tk.Frame(app, bg=CORES["bg_janela"], padx=24, pady=8)
rodape.pack(fill="x", side="bottom")

lbl_rodape = tk.Label(
    rodape,
    text="Inicializando...",
    font=("Segoe UI", 8),
    bg=CORES["bg_janela"],
    fg=CORES["texto_secundario"],
    anchor="w",
)
lbl_rodape.pack(fill="x")

atualizar_interface()
app.mainloop()
