// Relative-path fetch client (marketer dashboard pattern): prod is same-origin because FastAPI
// serves the build; dev goes through the Vite proxy. 401 is returned as {_unauth:true}, not thrown.
async function req(path, opts = {}) {
  const res = await fetch(path, { credentials: "include", ...opts });
  if (res.status === 401) return { _unauth: true };
  let body = null;
  try { body = await res.json(); } catch { /* empty body */ }
  if (!res.ok) return { _error: (body && body.detail) || `http_${res.status}` };
  return body;
}

export const get = (path) => req(path);
export const post = (path, data) =>
  req(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
