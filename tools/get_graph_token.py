"""
Ferramenta para autenticar via Microsoft Graph API (interativo + device code).

Execute UMA VEZ para obter o refresh token da caixa de e-mail monitorada.
O token gerado deve ser salvo no .env como GRAPH_REFRESH_TOKEN.

Pre-requisitos no Azure (app JDMS Automacao N1):
  - Permissao delegada: Mail.Read
  - Authentication -> "Allow public client flows" habilitado

Uso:
    cd project
    python tools/get_graph_token.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    import msal
except ImportError:
    print("ERRO: instale o msal primeiro:")
    print('  pip install "msal>=1.31.0"')
    sys.exit(1)

from utils.config import get_settings

SCOPES = ["https://graph.microsoft.com/Mail.Read"]


def _print_token_help(refresh_token: str) -> None:
    print("\nAutenticacao concluida com sucesso!")
    print("\nCopie o valor abaixo e adicione ao .env:")
    print("\nGRAPH_REFRESH_TOKEN=" + refresh_token)
    print("\nOu execute o comando abaixo para adicionar automaticamente:")
    env_path = PROJECT_ROOT / ".env"
    print(f'\n  echo GRAPH_REFRESH_TOKEN={refresh_token} >> "{env_path}"')


def main() -> None:
    settings = get_settings()

    tenant_id = settings.graph_tenant_id.strip()
    client_id = settings.graph_client_id.strip()

    if not tenant_id or not client_id:
        print("ERRO: Configure GRAPH_TENANT_ID e GRAPH_CLIENT_ID no .env antes de executar.")
        sys.exit(1)

    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
    )

    result = None

    # 1) Tenta interativo primeiro (evita problemas de conexao interrompida no polling).
    try:
        print("Iniciando autenticacao interativa (janela do navegador)...")
        result = app.acquire_token_interactive(scopes=SCOPES)
    except Exception as exc:
        print(f"Autenticacao interativa falhou: {exc}")
        print("Tentando Device Code Flow...")

    # 2) Fallback para Device Code Flow.
    if not result or "access_token" not in result:
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            print(f"ERRO ao iniciar autenticacao: {flow}")
            sys.exit(1)

        print("\n" + "=" * 60)
        print(flow["message"])
        print("=" * 60)
        print("\nAguardando autenticacao no navegador...")

        try:
            result = app.acquire_token_by_device_flow(flow)
        except Exception as exc:
            print("\nERRO de conexao durante Device Code Flow.")
            print("Causa provavel: proxy/firewall/instabilidade de rede.")
            print(f"Detalhe tecnico: {exc}")
            print("\nTente executar novamente em 10-20 segundos.")
            sys.exit(1)

    if "access_token" not in result:
        desc = result.get("error_description") or result.get("error") or str(result)
        print(f"\nERRO na autenticacao: {desc}")
        sys.exit(1)

    refresh_token = result.get("refresh_token", "")
    if not refresh_token:
        print("\nAVISO: refresh_token nao retornado. Verifique se 'offline_access' esta nos scopes.")
        print("O worker precisara de re-autenticacao periodica.")
    else:
        _print_token_help(refresh_token)


if __name__ == "__main__":
    main()
