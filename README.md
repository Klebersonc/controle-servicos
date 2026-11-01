# Controle de Serviços do Windows

Aplicação desktop em Python (`tkinter`) com tema escuro (Dark Theme) para monitorar, iniciar e parar serviços do Windows com privilégios de Administrador.

## Funcionalidades
- **Interface Moderna (Dark Theme):** Cartões individuais com indicadores visuais de status (`ATIVO` / `PARADO`) e descrição amigável automática do serviço.
- **Elevação Automática (UAC):** Solicita permissão de Administrador automaticamente ao iniciar.
- **Execução Assíncrona:** Comandos PowerShell executados em segundo plano (`threading`) sem travar a interface.
- **Monitoramento Automático:** Atualiza o status dos serviços automaticamente a cada 5 minutos.
- **Ações Individuais e em Lote:** Permite iniciar/parar cada serviço individualmente ou todos de uma vez.

## Como configurar os serviços
No arquivo `main.py` (linha 10), edite a lista `SERVICOS` com os nomes técnicos dos serviços do Windows que deseja gerenciar:

```python
SERVICOS = ["Spooler", "wuauserv"]
```

## Como executar
Dê duplo clique em `executar.bat` ou execute no terminal:

```powershell
python main.py
```
