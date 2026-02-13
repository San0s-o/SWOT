import { createClient } from "npm:@supabase/supabase-js@2";

function json(status: number, body: Record<string, unknown>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

async function sha256Hex(input: string): Promise<string> {
  const data = new TextEncoder().encode(input);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (req) => {
  if (req.method !== "POST") return json(405, { ok: false, message: "Method not allowed." });

  const supabaseUrl = Deno.env.get("SUPABASE_URL") ?? "";
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
  if (!supabaseUrl || !serviceRoleKey) {
    return json(500, { ok: false, message: "Server not configured." });
  }
  const supabase = createClient(supabaseUrl, serviceRoleKey);

  let body: any;
  try {
    body = await req.json();
  } catch {
    return json(400, { ok: false, message: "Invalid JSON body." });
  }

  const key = String(body?.key ?? "").trim();
  const sessionToken = String(body?.session_token ?? "").trim();
  const machineFingerprint = String(body?.machine_fingerprint ?? "").trim();
  const appId = String(body?.app_id ?? "SWOT").trim();
  if (!key || !sessionToken || !machineFingerprint || !appId) {
    return json(400, { ok: false, message: "Missing key, session_token, machine_fingerprint or app_id." });
  }

  const keyHash = await sha256Hex(key);
  const { data: license, error: licenseErr } = await supabase
    .from("licenses")
    .select("id,license_type,status,expires_at,max_devices,app_id")
    .eq("license_key_hash", keyHash)
    .eq("app_id", appId)
    .maybeSingle();
  if (licenseErr) return json(500, { ok: false, message: "License lookup failed." });
  if (!license) return json(401, { ok: false, message: "Lizenzschlüssel ungültig." });
  if (license.status !== "active") return json(403, { ok: false, message: "Lizenz ist deaktiviert." });
  if (license.expires_at && new Date(license.expires_at).getTime() <= Date.now()) {
    return json(403, { ok: false, message: "Lizenz ist abgelaufen." });
  }

  const { data: session, error: sessErr } = await supabase
    .from("license_sessions")
    .select("id,license_id,machine_fingerprint,expires_at")
    .eq("session_token", sessionToken)
    .maybeSingle();
  if (sessErr) return json(500, { ok: false, message: "Session lookup failed." });
  if (!session || session.license_id !== license.id) {
    return json(401, { ok: false, message: "Session ungültig." });
  }
  if (session.machine_fingerprint !== machineFingerprint) {
    return json(401, { ok: false, message: "Session gehört zu anderem Gerät." });
  }
  if (new Date(session.expires_at).getTime() <= Date.now()) {
    return json(401, { ok: false, message: "Session abgelaufen." });
  }

  const { data: activation } = await supabase
    .from("activations")
    .select("id")
    .eq("license_id", license.id)
    .eq("machine_fingerprint", machineFingerprint)
    .maybeSingle();
  if (!activation) return json(403, { ok: false, message: "Gerät ist nicht aktiviert." });

  const nowIso = new Date().toISOString();
  await supabase.from("license_sessions").update({ last_seen: nowIso }).eq("id", session.id);
  await supabase.from("activations").update({ last_seen: nowIso }).eq("id", activation.id);

  return json(200, {
    ok: true,
    message: "Lizenz gültig.",
    license_type: license.license_type,
    license_expires_at: license.expires_at,
    session_token: sessionToken,
    session_expires_at: session.expires_at,
  });
});

