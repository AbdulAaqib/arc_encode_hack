from __future__ import annotations

import os
from decimal import Decimal
from typing import Any, Callable, Dict, Optional, Tuple

from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError

from .messages import tool_success, tool_error
from .tx_helpers import fee_params, next_nonce, sign_and_send, metamask_tx_request

from ..config import PRIVATE_KEY_ENV


def build_lending_pool_toolkit(
    *,
    w3: Web3,
    pool_contract: Contract,
    token_decimals: int,
    native_decimals: int,
    private_key: Optional[str],
    default_gas_limit: int,
    gas_price_gwei: str,
    role_addresses: Optional[Dict[str, str]] = None,
    role_private_keys: Optional[Dict[str, Optional[str]]] = None,
) -> Tuple[list[Dict[str, Any]], Dict[str, Callable[..., str]]]:
    tools: list[Dict[str, Any]] = []
    handlers: Dict[str, Callable[..., str]] = {}

    derived_private_key = private_key or os.getenv(PRIVATE_KEY_ENV)
    role_private_keys = role_private_keys or {}
    role_addresses = role_addresses or {}

    def _acct_for_key(key: Optional[str]) -> Optional[str]:
        if not key:
            return None
        try:
            return w3.eth.account.from_key(key).address  # type: ignore[arg-type]
        except Exception:
            return None

    owner_key = role_private_keys.get("Owner") or derived_private_key
    lender_key = role_private_keys.get("Lender") or None
    borrower_key = role_private_keys.get("Borrower") or None

    owner_address = role_addresses.get("Owner") or _acct_for_key(owner_key)
    lender_address = role_addresses.get("Lender") or _acct_for_key(lender_key)
    borrower_address = role_addresses.get("Borrower") or _acct_for_key(borrower_key)

    def register(name: str, description: str, parameters: Dict[str, Any], handler: Callable[..., str]) -> None:
        tools.append({"type": "function", "function": {"name": name, "description": description, "parameters": parameters}})
        handlers[name] = handler

    def _metamask_success(tx_req: Dict[str, Any], hint: str, from_addr: Optional[str]) -> str:
        payload: Dict[str, Any] = {
            "metamask": {
                "tx_request": tx_req,
                "action": "eth_sendTransaction",
                "chainId": w3.eth.chain_id,
                "hint": hint,
            }
        }
        if from_addr:
            payload["metamask"]["from"] = from_addr
        return tool_success(payload)

    def _fees() -> Dict[str, int]:
        return fee_params(w3, gas_price_gwei)

    def _to_token_units(amount: float | int, *, use_native: bool = False) -> int:
        try:
            amt = Decimal(str(amount))
            scale = Decimal(10) ** int(native_decimals if use_native else token_decimals)
            return int(amt * scale)
        except Exception:
            return int(amount)

    def _from_token_units(amount: int, *, use_native: bool = False) -> Decimal:
        scale = Decimal(10) ** int(native_decimals if use_native else token_decimals)
        return (Decimal(amount) / scale) if amount else Decimal(0)

    def _loan_status(address: str) -> Optional[tuple[bool, int, int, int, int, bool]]:
        try:
            status_fn = getattr(pool_contract.functions, "loanStatus", None)
            if status_fn is not None:
                return status_fn(address).call()
            loan = getattr(pool_contract.functions, "getLoan")(address).call()
            principal, outstanding, start_time, due_time, active = loan
            banned_flag = bool(getattr(pool_contract.functions, "isBanned")(address).call())
            return bool(active), int(principal), int(outstanding), int(start_time), int(due_time), banned_flag
        except Exception:
            return None

    def _lender_status(address: str) -> Optional[tuple[int, int, int, int]]:
        try:
            status_fn = getattr(pool_contract.functions, "lenderStatus", None)
            if status_fn is not None:
                return status_fn(address).call()
            total_dep = int(getattr(pool_contract.functions, "totalDeposited")(address).call())
            total_withdrawn = int(getattr(pool_contract.functions, "totalWithdrawn")(address).call())
            balance = int(getattr(pool_contract.functions, "lenderBalance")(address).call())
            unlockable = int(getattr(pool_contract.functions, "previewWithdraw")(address).call())
            return total_dep, total_withdrawn, balance, unlockable
        except Exception:
            return None

    def _can_open_loan(address: str, principal_units: int) -> tuple[bool, str]:
        try:
            checker = getattr(pool_contract.functions, "canOpenLoan", None)
            if checker is None:
                loan = _loan_status(address)
                if loan is None:
                    return False, "Unable to read loan status"
                active, _, outstanding, _, _, banned_flag = loan
                if banned_flag:
                    return False, "Borrower is banned"
                if active and outstanding != 0:
                    human = _from_token_units(outstanding, use_native=True)
                    return False, f"Borrower has an active loan outstanding ({human} units)"
                available = int(getattr(pool_contract.functions, "availableLiquidity")().call())
                if available < principal_units:
                    return False, "Insufficient pool liquidity"
                return True, "OK"
            ok, reason = checker(address, principal_units).call()
            if isinstance(reason, (bytes, bytearray)):
                try:
                    reason = reason.decode("utf-8").rstrip("\x00")
                except Exception:
                    reason = reason.hex()
            return bool(ok), str(reason)
        except Exception as exc:
            return False, f"Unable to evaluate loan conditions: {exc}"

    # ---- Views ----
    def availableLiquidity_tool() -> str:
        try:
            amount = int(getattr(pool_contract.functions, "availableLiquidity")().call())
            return tool_success({"availableLiquidity": amount})
        except Exception as exc:
            return tool_error(f"Read failed: {exc}")

    register(
        "availableLiquidity",
        "Read pool's available liquidity (token balance).",
        {"type": "object", "properties": {}, "required": []},
        lambda: availableLiquidity_tool(),
    )

    def lenderBalance_tool(lender_address: str) -> str:
        try:
            lender = Web3.to_checksum_address(lender_address)
            amount = int(getattr(pool_contract.functions, "lenderBalance")(lender).call())
            return tool_success({"lender": lender, "balance": amount})
        except Exception as exc:
            return tool_error(f"Read failed: {exc}")

    register(
        "lenderBalance",
        "Read net balance (deposits - withdrawals) for a lender.",
        {
            "type": "object",
            "properties": {"lender_address": {"type": "string", "description": "Lender wallet address."}},
            "required": ["lender_address"],
        },
        lenderBalance_tool,
    )

    def lenderStatus_tool(lender_address: str) -> str:
        try:
            lender = Web3.to_checksum_address(lender_address)
        except ValueError:
            return tool_error("Invalid lender address supplied.")
        status = _lender_status(lender)
        if status is None:
            return tool_error("Unable to read lender status; ensure contract is upgraded.")
        total_dep, total_withdrawn, balance, unlockable = map(int, status)
        return tool_success(
            {
                "lender": lender,
                "totalDeposited": total_dep,
                "totalWithdrawn": total_withdrawn,
                "currentBalance": balance,
                "currentBalanceHuman": str(_from_token_units(balance, use_native=True)),
                "unlockable": unlockable,
                "unlockableHuman": str(_from_token_units(unlockable, use_native=True)),
            }
        )

    register(
        "lenderStatus",
        "Read aggregated lender metrics (deposited, withdrawn, unlockable).",
        {
            "type": "object",
            "properties": {"lender_address": {"type": "string", "description": "Lender wallet address."}},
            "required": ["lender_address"],
        },
        lenderStatus_tool,
    )

    def getLoan_tool(borrower_address: str) -> str:
        try:
            borrower = Web3.to_checksum_address(borrower_address)
            status = _loan_status(borrower)
            if status is None:
                return tool_error("Unable to read loan status for borrower.")
            active, principal, outstanding, start_time, due_time, banned_flag = status
            return tool_success(
                {
                    "borrower": borrower,
                    "principal": int(principal),
                    "outstanding": int(outstanding),
                    "outstandingHuman": str(_from_token_units(int(outstanding), use_native=True)),
                    "startTime": int(start_time),
                    "dueTime": int(due_time),
                    "active": bool(active),
                    "banned": bool(banned_flag),
                }
            )
        except Exception as exc:
            return tool_error(f"Read failed: {exc}")

    register(
        "getLoan",
        "Read loan struct for a borrower (principal, outstanding, startTime, dueTime, active).",
        {
            "type": "object",
            "properties": {"borrower_address": {"type": "string", "description": "Borrower wallet address."}},
            "required": ["borrower_address"],
        },
        getLoan_tool,
    )

    def isBanned_tool(borrower_address: str) -> str:
        try:
            borrower = Web3.to_checksum_address(borrower_address)
            banned = bool(getattr(pool_contract.functions, "isBanned")(borrower).call())
            return tool_success({"borrower": borrower, "banned": banned})
        except Exception as exc:
            return tool_error(f"Read failed: {exc}")

    register(
        "isBanned",
        "Check if a borrower is banned due to default.",
        {
            "type": "object",
            "properties": {"borrower_address": {"type": "string", "description": "Borrower wallet address."}},
            "required": ["borrower_address"],
        },
        isBanned_tool,
    )

    # ---- Writes ----
    def deposit_tool(amount: float | int) -> str:
        try:
            amt_decimal = Decimal(str(amount))
        except Exception:
            return tool_error("Invalid amount supplied; enter a numeric value.")
        if amt_decimal <= Decimal("0"):
            return tool_error("Amount must be greater than zero.")
        try:
            amt = _to_token_units(amt_decimal, use_native=True)
        except Exception as exc:
            return tool_error(f"Invalid amount: {exc}")

        signer = _acct_for_key(lender_key)
        if signer and lender_key:
            try:
                tx = pool_contract.functions.deposit(amt).build_transaction(
                    {
                        "from": signer,
                        "nonce": next_nonce(w3, signer),
                        "gas": default_gas_limit,
                        "chainId": w3.eth.chain_id,
                        "value": amt,
                        **_fees(),
                    }
                )
                sent = sign_and_send(w3, lender_key, tx)  # type: ignore[arg-type]
                return tool_success(sent) if "error" not in sent else tool_error(sent.get("error", "deposit failed"))
            except ContractLogicError as exc:
                return tool_error(f"Contract rejected: {exc}")
            except Exception as exc:
                return tool_error(f"deposit failed: {exc}")

        if lender_address:
            try:
                tx_req = metamask_tx_request(
                    pool_contract,
                    "deposit",
                    [amt],
                    value_wei=amt,
                    from_address=lender_address,
                )
                return _metamask_success(
                    tx_req,
                    "Use MetaMask (lender wallet) to deposit native USDC into the pool.",
                    lender_address,
                )
            except Exception as exc:
                return tool_error(f"Unable to build MetaMask tx: {exc}")

        return tool_error(
            "Lender wallet not configured. Assign a lender address via MetaMask role assignment or set LENDER_PRIVATE_KEY."
        )

    register(
        "deposit",
        "Deposit USDC into the LendingPool (requires prior approve).",
        {
            "type": "object",
            "properties": {"amount": {"type": "number", "description": "Amount in human units (e.g., 100 USDC)."}},
            "required": ["amount"],
        },
        deposit_tool,
    )

    def withdraw_tool(amount: float | int) -> str:
        try:
            amt_decimal = Decimal(str(amount))
        except Exception:
            return tool_error("Invalid amount supplied; enter a numeric value.")
        if amt_decimal <= Decimal("0"):
            return tool_error("Amount must be greater than zero.")
        try:
            amt = _to_token_units(amt_decimal, use_native=True)
        except Exception as exc:
            return tool_error(f"Invalid amount: {exc}")

        status_address: Optional[str] = None
        if lender_address:
            try:
                status_address = Web3.to_checksum_address(lender_address)
            except ValueError:
                status_address = None
        if status_address is None:
            signer = _acct_for_key(lender_key)
            if signer:
                try:
                    status_address = Web3.to_checksum_address(signer)
                except ValueError:
                    status_address = None

        if status_address:
            status = _lender_status(status_address)
            if status is not None:
                _, _, _, unlockable = map(int, status)
                if amt > unlockable:
                    human_unlockable = _from_token_units(unlockable, use_native=True)
                    return tool_error(
                        f"Requested withdrawal exceeds unlocked balance ({human_unlockable} available)."
                    )

        signer = _acct_for_key(lender_key)
        if signer and lender_key:
            try:
                tx = pool_contract.functions.withdraw(amt).build_transaction(
                    {
                        "from": signer,
                        "nonce": next_nonce(w3, signer),
                        "gas": default_gas_limit,
                        "chainId": w3.eth.chain_id,
                        **_fees(),
                    }
                )
                sent = sign_and_send(w3, lender_key, tx)  # type: ignore[arg-type]
                return tool_success(sent) if "error" not in sent else tool_error(sent.get("error", "withdraw failed"))
            except ContractLogicError as exc:
                return tool_error(f"Contract rejected: {exc}")
            except Exception as exc:
                return tool_error(f"withdraw failed: {exc}")

        if lender_address:
            try:
                tx_req = metamask_tx_request(
                    pool_contract,
                    "withdraw",
                    [amt],
                    from_address=lender_address,
                )
                return _metamask_success(
                    tx_req,
                    "Use MetaMask (lender wallet) to withdraw unlocked funds.",
                    lender_address,
                )
            except Exception as exc:
                return tool_error(f"Unable to build MetaMask tx: {exc}")

        return tool_error(
            "Lender wallet not configured. Assign a lender address via MetaMask role assignment or set LENDER_PRIVATE_KEY."
        )

    register(
        "withdraw",
        "Withdraw available USDC from the LendingPool (subject to liquidity/locks).",
        {
            "type": "object",
            "properties": {"amount": {"type": "number", "description": "Amount in human units."}},
            "required": ["amount"],
        },
        withdraw_tool,
    )

    def openLoan_tool(borrower_address: str, principal: float | int, term_seconds: int) -> str:
        try:
            borrower = Web3.to_checksum_address(borrower_address)
        except ValueError:
            return tool_error("Invalid borrower address supplied.")
        try:
            principal_decimal = Decimal(str(principal))
        except Exception:
            return tool_error("Invalid principal supplied; enter a numeric value.")
        if principal_decimal <= Decimal("0"):
            return tool_error("Principal must be greater than zero.")
        try:
            principal_units = _to_token_units(principal_decimal, use_native=True)
        except Exception as exc:
            return tool_error(f"Invalid principal: {exc}")

        ok, reason = _can_open_loan(borrower, principal_units)
        if not ok:
            lower_reason = reason.lower()
            if "active loan" in lower_reason:
                status = _loan_status(borrower)
                if status is not None:
                    _, _, outstanding, _, _, _ = status
                    human_outstanding = _from_token_units(int(outstanding), use_native=True)
                    return tool_error(
                        f"Cannot open loan: borrower has an active loan outstanding ({human_outstanding} native units)."
                    )
            return tool_error(f"Cannot open loan: {reason}")

        signer = _acct_for_key(owner_key)
        if signer and owner_key:
            try:
                fees = _fees()
                nonce = next_nonce(w3, signer)
                tx = pool_contract.functions.openLoan(borrower, principal_units, int(term_seconds)).build_transaction(
                    {
                        "from": signer,
                        "nonce": nonce,
                        "gas": default_gas_limit,
                        "chainId": w3.eth.chain_id,
                        **fees,
                    }
                )
                sent = sign_and_send(w3, owner_key, tx)  # type: ignore[arg-type]
                return tool_success(sent) if "error" not in sent else tool_error(sent.get("error", "openLoan failed"))
            except ContractLogicError as exc:
                return tool_error(f"Contract rejected: {exc}")
            except Exception as exc:
                return tool_error(f"openLoan failed: {exc}")

        if owner_address:
            try:
                tx_req = metamask_tx_request(
                    pool_contract,
                    "openLoan",
                    [borrower, principal_units, int(term_seconds)],
                    from_address=owner_address,
                )
                return _metamask_success(
                    tx_req,
                    "Use MetaMask (owner wallet) to open a loan.",
                    owner_address,
                )
            except Exception as exc:
                return tool_error(f"Unable to build MetaMask tx: {exc}")

        return tool_error(
            "Owner wallet not configured. Assign an owner address via MetaMask role assignment or set PRIVATE_KEY."
        )

    register(
        "openLoan",
        "Owner-only: open a loan for borrower and transfer principal.",
        {
            "type": "object",
            "properties": {
                "borrower_address": {"type": "string", "description": "Borrower wallet address."},
                "principal": {"type": "number", "description": "Principal in human units (e.g., 50 USDC)."},
                "term_seconds": {"type": "integer", "description": "Loan term in seconds (e.g., 604800 for 7 days)."},
            },
            "required": ["borrower_address", "principal", "term_seconds"],
        },
        openLoan_tool,
    )

    def repay_tool() -> str:
        borrower_addr = borrower_address or _acct_for_key(borrower_key)
        if not borrower_addr:
            return tool_error(
                "Borrower wallet not configured. Assign a borrower address via MetaMask role assignment or set BORROWER_PRIVATE_KEY."
            )

        try:
            borrower = Web3.to_checksum_address(borrower_addr)
        except ValueError:
            return tool_error("Borrower address is not valid.")

        status = _loan_status(borrower)
        if status is None:
            return tool_error("Unable to read borrower loan status; ensure contract is upgraded.")
        active, _, outstanding, _, _, banned_flag = status
        if banned_flag:
            return tool_error("Borrower is banned; repay unavailable until unbanned.")
        if not active or outstanding == 0:
            return tool_error("No active loan to repay.")

        amt = int(outstanding)
        amt_decimal = _from_token_units(amt, use_native=True)
        hint = f"Repay outstanding balance ({amt_decimal} in native units)."

        signer = _acct_for_key(borrower_key)
        if signer and borrower_key:
            try:
                tx = pool_contract.functions.repay(amt).build_transaction(
                    {
                        "from": signer,
                        "nonce": next_nonce(w3, signer),
                        "gas": default_gas_limit,
                        "chainId": w3.eth.chain_id,
                        "value": amt,
                        **_fees(),
                    }
                )
                sent = sign_and_send(w3, borrower_key, tx)  # type: ignore[arg-type]
                if "error" in sent:
                    return tool_error(sent.get("error", "repay failed"))
                sent.setdefault("hint", hint)
                return tool_success(sent)
            except ContractLogicError as exc:
                return tool_error(f"Contract rejected: {exc}")
            except Exception as exc:
                return tool_error(f"repay failed: {exc}")

        if borrower_address:
            try:
                tx_req = metamask_tx_request(
                    pool_contract,
                    "repay",
                    [amt],
                    value_wei=amt,
                    from_address=borrower_address,
                )
                return _metamask_success(
                    tx_req,
                    hint,
                    borrower_address,
                )
            except Exception as exc:
                return tool_error(f"Unable to build MetaMask tx: {exc}")

        return tool_error(
            "Borrower wallet not configured. Assign a borrower address via MetaMask role assignment or set BORROWER_PRIVATE_KEY."
        )

    register(
        "repay",
        "Borrower: repay outstanding loan balance (full payoff only).",
        {
            "type": "object",
            "properties": {},
            "required": [],
        },
        repay_tool,
    )

    def checkDefaultAndBan_tool(borrower_address: str) -> str:
        signer = _acct_for_key(owner_key)
        try:
            borrower = Web3.to_checksum_address(borrower_address)
        except ValueError:
            return tool_error("Invalid borrower address supplied.")
        if signer and owner_key:
            try:
                fees = _fees()
                nonce = next_nonce(w3, signer)
                tx = pool_contract.functions.checkDefaultAndBan(borrower).build_transaction(
                    {
                        "from": signer,
                        "nonce": nonce,
                        "gas": default_gas_limit,
                        "chainId": w3.eth.chain_id,
                        **fees,
                    }
                )
                sent = sign_and_send(w3, owner_key, tx)  # type: ignore[arg-type]
                return tool_success(sent) if "error" not in sent else tool_error(sent.get("error", "checkDefaultAndBan failed"))
            except ContractLogicError as exc:
                return tool_error(f"Contract rejected: {exc}")
            except Exception as exc:
                return tool_error(f"checkDefaultAndBan failed: {exc}")

        if owner_address:
            try:
                tx_req = metamask_tx_request(
                    pool_contract,
                    "checkDefaultAndBan",
                    [borrower],
                    from_address=owner_address,
                )
                return _metamask_success(
                    tx_req,
                    "Use MetaMask (owner wallet) to check default and ban overdue borrower.",
                    owner_address,
                )
            except Exception as exc:
                return tool_error(f"Unable to build MetaMask tx: {exc}")

        return tool_error(
            "Owner wallet not configured. Assign an owner address via MetaMask role assignment or set PRIVATE_KEY."
        )

    register(
        "checkDefaultAndBan",
        "Anyone: check if borrower defaulted and ban if overdue.",
        {
            "type": "object",
            "properties": {"borrower_address": {"type": "string", "description": "Borrower wallet address."}},
            "required": ["borrower_address"],
        },
        checkDefaultAndBan_tool,
    )

    def setDepositLockSeconds_tool(seconds: int) -> str:
        signer = _acct_for_key(owner_key)
        if signer and owner_key:
            try:
                tx = pool_contract.functions.setDepositLockSeconds(int(seconds)).build_transaction(
                    {
                        "from": signer,
                        "nonce": next_nonce(w3, signer),
                        "gas": default_gas_limit,
                        "chainId": w3.eth.chain_id,
                        **_fees(),
                    }
                )
                sent = sign_and_send(w3, owner_key, tx)  # type: ignore[arg-type]
                return tool_success(sent) if "error" not in sent else tool_error(sent.get("error", "setDepositLockSeconds failed"))
            except ContractLogicError as exc:
                return tool_error(f"Contract rejected: {exc}")
            except Exception as exc:
                return tool_error(f"setDepositLockSeconds failed: {exc}")

        if owner_address:
            try:
                tx_req = metamask_tx_request(
                    pool_contract,
                    "setDepositLockSeconds",
                    [int(seconds)],
                    from_address=owner_address,
                )
                return _metamask_success(
                    tx_req,
                    "Use MetaMask (owner wallet) to update deposit lock duration.",
                    owner_address,
                )
            except Exception as exc:
                return tool_error(f"Unable to build MetaMask tx: {exc}")

        return tool_error(
            "Owner wallet not configured. Assign an owner address via MetaMask role assignment or set PRIVATE_KEY."
        )

    register(
        "setDepositLockSeconds",
        "Owner-only: set global deposit lock duration in seconds.",
        {
            "type": "object",
            "properties": {"seconds": {"type": "integer", "description": "Lock duration in seconds (0 to disable)."}},
            "required": ["seconds"],
        },
        setDepositLockSeconds_tool,
    )

    def setTrustMintSbt_tool(sbt_address: str) -> str:
        try:
            sbt = Web3.to_checksum_address(sbt_address)
        except ValueError:
            return tool_error("Invalid SBT address supplied.")

        signer = _acct_for_key(owner_key)
        if signer and owner_key:
            try:
                tx = pool_contract.functions.setTrustMintSbt(sbt).build_transaction(
                    {
                        "from": signer,
                        "nonce": next_nonce(w3, signer),
                        "gas": default_gas_limit,
                        "chainId": w3.eth.chain_id,
                        **_fees(),
                    }
                )
                sent = sign_and_send(w3, owner_key, tx)  # type: ignore[arg-type]
                return tool_success(sent) if "error" not in sent else tool_error(sent.get("error", "setTrustMintSbt failed"))
            except ContractLogicError as exc:
                return tool_error(f"Contract rejected: {exc}")
            except Exception as exc:
                return tool_error(f"setTrustMintSbt failed: {exc}")

        if owner_address:
            try:
                tx_req = metamask_tx_request(
                    pool_contract,
                    "setTrustMintSbt",
                    [sbt],
                    from_address=owner_address,
                )
                return _metamask_success(
                    tx_req,
                    "Use MetaMask (owner wallet) to set TrustMint SBT address (0x0 to disable).",
                    owner_address,
                )
            except Exception as exc:
                return tool_error(f"Unable to build MetaMask tx: {exc}")

        return tool_error(
            "Owner wallet not configured. Assign an owner address via MetaMask role assignment or set PRIVATE_KEY."
        )

    register(
        "setTrustMintSbt",
        "Owner-only: set TrustMint SBT address for score gating (0x0 to disable).",
        {
            "type": "object",
            "properties": {"sbt_address": {"type": "string", "description": "SBT contract address or 0x000... to disable."}},
            "required": ["sbt_address"],
        },
        setTrustMintSbt_tool,
    )

    def setMinScoreToBorrow_tool(new_min_score: int) -> str:
        signer = _acct_for_key(owner_key)
        if signer and owner_key:
            try:
                tx = pool_contract.functions.setMinScoreToBorrow(int(new_min_score)).build_transaction(
                    {
                        "from": signer,
                        "nonce": next_nonce(w3, signer),
                        "gas": default_gas_limit,
                        "chainId": w3.eth.chain_id,
                        **_fees(),
                    }
                )
                sent = sign_and_send(w3, owner_key, tx)  # type: ignore[arg-type]
                return tool_success(sent) if "error" not in sent else tool_error(sent.get("error", "setMinScoreToBorrow failed"))
            except ContractLogicError as exc:
                return tool_error(f"Contract rejected: {exc}")
            except Exception as exc:
                return tool_error(f"setMinScoreToBorrow failed: {exc}")

        if owner_address:
            try:
                tx_req = metamask_tx_request(
                    pool_contract,
                    "setMinScoreToBorrow",
                    [int(new_min_score)],
                    from_address=owner_address,
                )
                return _metamask_success(
                    tx_req,
                    "Use MetaMask (owner wallet) to set minimum score for borrowing.",
                    owner_address,
                )
            except Exception as exc:
                return tool_error(f"Unable to build MetaMask tx: {exc}")

        return tool_error(
            "Owner wallet not configured. Assign an owner address via MetaMask role assignment or set PRIVATE_KEY."
        )

    register(
        "setMinScoreToBorrow",
        "Owner-only: set minimum score threshold for borrowing.",
        {
            "type": "object",
            "properties": {"new_min_score": {"type": "integer", "description": "Minimum score required."}},
            "required": ["new_min_score"],
        },
        setMinScoreToBorrow_tool,
    )

    def unban_tool(borrower_address: str) -> str:
        try:
            borrower = Web3.to_checksum_address(borrower_address)
        except ValueError:
            return tool_error("Invalid borrower address supplied.")

        signer = _acct_for_key(owner_key)
        if signer and owner_key:
            try:
                tx = pool_contract.functions.unban(borrower).build_transaction(
                    {
                        "from": signer,
                        "nonce": next_nonce(w3, signer),
                        "gas": default_gas_limit,
                        "chainId": w3.eth.chain_id,
                        **_fees(),
                    }
                )
                sent = sign_and_send(w3, owner_key, tx)  # type: ignore[arg-type]
                return tool_success(sent) if "error" not in sent else tool_error(sent.get("error", "unban failed"))
            except ContractLogicError as exc:
                return tool_error(f"Contract rejected: {exc}")
            except Exception as exc:
                return tool_error(f"unban failed: {exc}")

        if owner_address:
            try:
                tx_req = metamask_tx_request(
                    pool_contract,
                    "unban",
                    [borrower],
                    from_address=owner_address,
                )
                return _metamask_success(
                    tx_req,
                    "Use MetaMask (owner wallet) to unban borrower after remedy.",
                    owner_address,
                )
            except Exception as exc:
                return tool_error(f"Unable to build MetaMask tx: {exc}")

        return tool_error(
            "Owner wallet not configured. Assign an owner address via MetaMask role assignment or set PRIVATE_KEY."
        )

    register(
        "unban",
        "Owner-only: unban a borrower after remedy.",
        {
            "type": "object",
            "properties": {"borrower_address": {"type": "string", "description": "Borrower wallet address."}},
            "required": ["borrower_address"],
        },
        unban_tool,
    )

    return tools, handlers

