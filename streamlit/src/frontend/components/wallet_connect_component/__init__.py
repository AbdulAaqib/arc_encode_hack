import os
from pathlib import Path
from typing import Any, Optional

import streamlit as st
import streamlit.components.v1 as components

# Streamlit custom component: Wallet Connect (React)
# Usage in pages:
#   from .wallet_connect_component import connect_wallet
#   info = connect_wallet(key="wallet_connect")
#   if isinstance(info, dict) and info.get("address"):
#       st.session_state["wallet_address"] = info["address"]


def _declare_component() -> Any:
    """Declare the Streamlit component.

    - Prefer static assets under `frontend/build` so no dev server is required.
    - Allow overriding with `WALLET_CONNECT_DEV_URL` during local development.
    """
    dev_url = os.getenv("WALLET_CONNECT_DEV_URL")
    if dev_url:
        return components.declare_component("wallet_connect", url=dev_url)

    build_dir = Path(__file__).parent / "frontend" / "build"
    index_html = build_dir / "index.html"
    if not index_html.exists():
        raise RuntimeError(
            "Wallet Connect component build not found.\n"
            "Run the frontend build once before using the component:\n"
            f"  cd {build_dir.parent}\n"
            "  npm install\n"
            "  npm run build"
        )

    return components.declare_component("wallet_connect", path=str(build_dir))


_component = _declare_component()


def connect_wallet(key: Optional[str] = None, require_chain_id: Optional[int] = None) -> Any:
    """Render the wallet connect UI and return the payload from the frontend."""
    return _component(default=None, key=key, require_chain_id=require_chain_id)


if __name__ == "__main__":
    st.title("Wallet Connect Component Preview")
    info = connect_wallet(key="wallet_connect")
    st.write(info)
