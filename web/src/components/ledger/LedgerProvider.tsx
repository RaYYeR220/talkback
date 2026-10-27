"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { LedgerDrawer } from "./LedgerDrawer";

interface LedgerApi {
  open: (cueId: string) => void;
}

const LedgerContext = createContext<LedgerApi | null>(null);

/** Lets any cue on the page open the claim ledger drawer. */
export function LedgerProvider({ children }: { children: ReactNode }) {
  const [cueId, setCueId] = useState<string | null>(null);
  const open = useCallback((id: string) => setCueId(id), []);
  const value = useMemo(() => ({ open }), [open]);
  return (
    <LedgerContext.Provider value={value}>
      {children}
      <LedgerDrawer cueId={cueId} onClose={() => setCueId(null)} />
    </LedgerContext.Provider>
  );
}

export function useLedger(): LedgerApi | null {
  return useContext(LedgerContext);
}
