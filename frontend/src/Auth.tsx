import { useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { authConfigured, supabase } from "./supabase";
import { deleteMyData } from "./api";

/**
 * Sign in / sign up, and the signed-in header.
 *
 * Passwords are handled entirely by Supabase — we never see or store one. Note
 * the confirmation case: this project has email confirmation enabled, so a new
 * signup gets a user but *no session* until the link is clicked. That state is
 * called out explicitly, because otherwise signing up looks like it silently
 * failed.
 */
export default function Auth({
  session,
  onChange,
}: {
  session: Session | null;
  onChange: () => void;
}) {
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(false);

  if (!authConfigured) {
    return (
      <p className="auth-note">
        Sign-in is unconfigured — set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.
      </p>
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setMsg(null);
    setBusy(true);
    try {
      if (mode === "up") {
        const { data, error } = await supabase!.auth.signUp({ email, password });
        if (error) throw error;
        // No session means the project requires email confirmation first.
        if (!data.session) {
          setMsg(`Check ${email} for a confirmation link, then sign in.`);
          setMode("in");
        } else {
          onChange();
        }
      } else {
        const { error } = await supabase!.auth.signInWithPassword({ email, password });
        if (error) throw error;
        onChange();
      }
      setPassword("");
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    await supabase!.auth.signOut();
    onChange();
  }

  async function forgetMe() {
    if (!window.confirm("Delete your library? This cannot be undone.")) return;
    setBusy(true);
    try {
      const n = await deleteMyData();
      setMsg(`Deleted ${n} librar${n === 1 ? "y entry" : "y entries"}.`);
      onChange();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : String(e2));
    } finally {
      setBusy(false);
    }
  }

  if (session) {
    return (
      <div className="auth-bar">
        <span className="auth-who">{session.user.email}</span>
        <button className="auth-link" onClick={signOut}>Sign out</button>
        <button className="auth-link auth-danger" onClick={forgetMe} disabled={busy}>
          Delete my data
        </button>
        {msg && <span className="auth-msg">{msg}</span>}
        {err && <span className="auth-err">{err}</span>}
      </div>
    );
  }

  if (!open) {
    return (
      <div className="auth-bar">
        <button className="auth-link" onClick={() => setOpen(true)}>
          Sign in to keep a library
        </button>
        {msg && <span className="auth-msg">{msg}</span>}
      </div>
    );
  }

  return (
    <form className="auth-form" onSubmit={submit}>
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="you@example.com"
        autoComplete="email"
        required
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        placeholder="password"
        autoComplete={mode === "up" ? "new-password" : "current-password"}
        minLength={6}
        required
      />
      <button className="go" disabled={busy}>
        {busy ? "…" : mode === "in" ? "Sign in" : "Sign up"}
      </button>
      <button
        type="button"
        className="auth-link"
        onClick={() => {
          setMode(mode === "in" ? "up" : "in");
          setErr(null);
        }}
      >
        {mode === "in" ? "Create an account" : "I have an account"}
      </button>
      <button type="button" className="auth-link" onClick={() => setOpen(false)}>
        Cancel
      </button>
      {msg && <p className="auth-msg">{msg}</p>}
      {err && <p className="auth-err">{err}</p>}
    </form>
  );
}
