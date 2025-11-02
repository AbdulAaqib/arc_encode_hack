import React, { useCallback, useEffect, useMemo, useState } from "react"
import { Streamlit } from "streamlit-component-lib"
import { useRenderData } from "streamlit-component-lib-react-hooks"

declare global {
  interface Window {
    ethereum?: any
  }
}

function shorten(addr?: string): string {
  if (!addr) {
    return ""
  }
  return `${addr.slice(0, 6)}...${addr.slice(-4)}`
}

type WalletInfo = {
  address?: string
  chainId?: string
  isConnected: boolean
  error?: string
}

export default function WalletConnect(): JSX.Element {
  const renderData = useRenderData()
  const disabled = !!renderData.disabled
  const theme = renderData.theme
  const requireChainId = renderData.args?.["require_chain_id"] as
    | number
    | string
    | undefined

  const [info, setInfo] = useState<WalletInfo>({ isConnected: false })

  const setValue = useCallback((payload: unknown) => {
    Streamlit.setComponentValue(payload)
  }, [])

  const handleAccountsChanged = useCallback(
    (accounts: string[]) => {
      if (accounts && accounts.length > 0) {
        const address = accounts[0]
        setInfo(prev => ({ ...prev, address, isConnected: true, error: undefined }))
        setValue({ address, chainId: info.chainId, isConnected: true })
      } else {
        setInfo({ isConnected: false })
        setValue({ isConnected: false })
      }
    },
    [info.chainId, setValue],
  )

  const handleChainChanged = useCallback(
    (chainId: string) => {
      setInfo(prev => ({ ...prev, chainId }))
      setValue({ address: info.address, chainId, isConnected: !!info.address })
    },
    [info.address, setValue],
  )

  const connect = useCallback(async () => {
    const eth = window.ethereum
    if (!eth) {
      const msg = "No injected wallet found. Install MetaMask to continue."
      setInfo({ isConnected: false, error: msg })
      setValue({ isConnected: false, error: msg })
      return
    }

    try {
      const accounts: string[] = await eth.request({ method: "eth_requestAccounts" })
      const chainId: string = await eth.request({ method: "eth_chainId" })
      const address = accounts?.[0]
      if (address) {
        setInfo({ address, chainId, isConnected: true })
        setValue({ address, chainId, isConnected: true })
      }
    } catch (e: any) {
      const msg = e?.message ?? String(e)
      setInfo({ isConnected: false, error: msg })
      setValue({ isConnected: false, error: msg })
    }
  }, [setValue])

  const disconnect = useCallback(() => {
    setInfo({ isConnected: false })
    setValue({ isConnected: false })
  }, [setValue])

  useEffect(() => {
    const eth = window.ethereum
    if (!(eth?.on)) {
      return
    }
    eth.on("accountsChanged", handleAccountsChanged)
    eth.on("chainChanged", handleChainChanged)
    return () => {
      eth?.removeListener?.("accountsChanged", handleAccountsChanged)
      eth?.removeListener?.("chainChanged", handleChainChanged)
    }
  }, [handleAccountsChanged, handleChainChanged])

  const button = useMemo(() => {
    if (info.isConnected) {
      return (
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <span style={{ fontFamily: "monospace" }}>{shorten(info.address)}</span>
          <button onClick={disconnect} disabled={disabled}>
            Disconnect
          </button>
        </div>
      )
    }
    return (
      <button onClick={connect} disabled={disabled}>
        Connect Wallet
      </button>
    )
  }, [info.isConnected, info.address, disconnect, connect, disabled])

  const borderColor = theme?.primaryColor ?? "#ddd"
  const chainMismatch = useMemo(() => {
    if (!requireChainId || !info.chainId) {
      return false
    }
    const expected = String(requireChainId).toLowerCase()
    return String(info.chainId).toLowerCase() !== expected
  }, [requireChainId, info.chainId])

  return (
    <div
      style={{
        fontFamily:
          "system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Helvetica, Arial, sans-serif",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        border: `1px solid ${borderColor}`,
        padding: 8,
        borderRadius: 6,
      }}
    >
      {button}
      {info.chainId && <div style={{ fontSize: 12, color: "#888" }}>Chain: {info.chainId}</div>}
      {chainMismatch && (
        <div style={{ fontSize: 12, color: "darkorange" }}>
          Expected chain {String(requireChainId)}, but connected to {String(info.chainId)}
        </div>
      )}
      {info.error && (
        <div style={{ marginTop: 6, color: "crimson", fontSize: 12 }}>{info.error}</div>
      )}
    </div>
  )
}
