# ⚡ ServiceGuard • Controle de Serviços do Windows

> **Desenvolvido por Kleberson Cordeiro**

Aplicação desktop em Python (`tkinter`) com visual de Dashboard (**Obsidian & Cyber Indigo**) para monitorar, iniciar e parar serviços do Windows, selecionar serviços em uma aba exclusiva e forçar automaticamente sua inicialização junto com o sistema operacional.

---

## ✨ Principais Funcionalidades

- **⭐ Aba Exclusiva `INICIAR PELO APP (MEUS)`:**
  - Lista apenas os serviços que você selecionou dentro do aplicativo clicando em **`⭐ + Iniciar pelo App`**.
  - A seleção fica salva localmente em `servicos_selecionados.json`.
  - Sempre que o aplicativo inicia (especialmente junto com o boot do Windows), ele verifica e **força automaticamente a inicialização** de todos os serviços selecionados nesta aba.
  - Conta com botões de ação rápida em lote: **`🚀 Forçar Início de Todos Agora`** e **`■ Parar Todos da Aba`**.
- **🟢 Iniciar o Aplicativo com o Windows:**
  - Botão superior **`🟢 Iniciar com o Windows: ATIVADO / DESATIVADO`** que cria ou remove a Tarefa Agendada `ControleServicosWindowsBoot` (gatilho no logon, 20s de atraso, `RunLevel Highest`).
  - O app abre já como Administrador no boot e força os serviços **sem pedir UAC**. O UAC é solicitado apenas uma vez, ao ativar/desativar.
- **📊 Painel de Indicadores (4 Abas / KPIs Interativos):**
  - **⭐ INICIAR PELO APP (MEUS):** Serviços escolhidos pelo usuário no App.
  - **📋 TODOS OS SERVIÇOS:** Lista completa de serviços instalados no Windows.
  - **● EM EXECUÇÃO (ATIVOS):** Apenas serviços em execução no momento (`Running`).
  - **○ SERVIÇOS PARADOS:** Apenas serviços parados (`Stopped`).
- **🎛 Controle Individual e Busca Instantânea:**
  - Botões dedicados **`▶ Iniciar`**, **`■ Parar`** e **`⭐ + Iniciar pelo App`** / **`★ Remover da Aba`** em cada cartão.
  - Pesquisa em tempo real pelo nome amigável (`DisplayName`) ou nome técnico (`Name`).
  - Janela redimensionável/maximizável com ajuste automático da quantidade de cartões exibidos na tela.
- **🛡 Elevação UAC Inteligente e Instância Única:**
  - Proteção por *Named Mutex* do Windows para impedir abertura duplicada.
  - Comandos administrativos executados via PowerShell `-EncodedCommand` (UTF-16LE Base64) e consulta rápida de status via `sc.exe query`.

---

## 🚀 Como Executar

Dê um duplo clique no arquivo [`executar.bat`](./executar.bat) ou execute no terminal:

```powershell
.\executar.bat
```

Ou diretamente via `uv` / Python:

```powershell
uv run pythonw main.py
```

---

## 👨‍💻 Autor

**Desenvolvido por Kleberson Cordeiro**
