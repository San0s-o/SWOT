import { createClient } from "npm:@supabase/supabase-js@2";

const SESSION_TTL_HOURS = Number(Deno.env.get("LICENSE_SESSION_TTL_HOURS") ?? "24");

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

function isoAfterHours(hours: number): string {
  const d = new Date();
  d.setHours(d.getHours() + hours);
  return d.toISOString();
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
  const machineFingerprint = String(body?.machine_fingerprint ?? "").trim();
  const appId = String(body?.app_id ?? "SWOT").trim();
  if (!key || !machineFingerprint || !appId) {
    return json(400, { ok: false, message: "Missing key, machine_fingerprint or app_id." });
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

  const { data: existingActivation } = await supabase
    .from("activations")
    .select("id")
    .eq("license_id", license.id)
    .eq("machine_fingerprint", machineFingerprint)
    .maybeSingle();

  if (!existingActivation) {
    const { count } = await supabase
      .from("activations")
      .select("*", { count: "exact", head: true })
      .eq("license_id", license.id);
    const activeDevices = Number(count ?? 0);
    if (activeDevices >= Number(license.max_devices ?? 1)) {
      return json(403, { ok: false, message: "Lizenz bereits auf anderem Gerät aktiviert." });
    }

    const { error: insActErr } = await supabase
      .from("activations")
      .insert({ license_id: license.id, machine_fingerprint: machineFingerprint });
    if (insActErr) return json(500, { ok: false, message: "Activation insert failed." });
  } else {
    await supabase
      .from("activations")
      .update({ last_seen: new Date().toISOString() })
      .eq("id", existingActivation.id);
  }

  const sessionToken = `${crypto.randomUUID()}${crypto.randomUUID()}`.replaceAll("-", "");
  const expiresAt = isoAfterHours(SESSION_TTL_HOURS);
  const { error: insSessionErr } = await supabase.from("license_sessions").insert({
    license_id: license.id,
    machine_fingerprint: machineFingerprint,
    session_token: sessionToken,
    expires_at: expiresAt,
  });
  if (insSessionErr) return json(500, { ok: false, message: "Session creation failed." });

  return json(200, {
    ok: true,
    message: "Lizenz aktiviert.",
    license_type: license.license_type,
    license_expires_at: license.expires_at,
    session_token: sessionToken,
    session_expires_at: expiresAt,
  });
});

