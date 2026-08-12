import type { SignSegment } from "../sign/SignSegment";
import { APP_CONFIG } from "../config/appConfig";

// VITE_API_URL is set in .env.example (e.g. http://127.0.0.1:8000). When
// unset, we fall back to /api/* which Vite proxies to the backend in dev
// and which a production reverse-proxy should handle.
const API_BASE = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";
const ENDPOINT = API_BASE ? `${API_BASE}/translate` : "/api/translate";

const DEFAULT_TIMEOUT_MS = APP_CONFIG.timeoutMs;

interface TranslateResponse {
    gloss: string[];
    segments: SignSegment[];
}

export interface TranslateOptions {
    /** Abort the request externally (e.g. user re-submits). */
    signal?: AbortSignal;
    /** Timeout in ms (default 8000). */
    timeoutMs?: number;
}

/**
 * Translate free text into per-word sign segments.
 *
 * Returns `segments` rather than the flat `gloss` list: the UI needs to know
 * which word each gesture belongs to in order to caption playback.
 */
export async function translate(text: string, options: TranslateOptions = {}): Promise<SignSegment[]> {
    const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => {
        controller.abort(new DOMException(`Translation timed out after ${timeoutMs}ms`, "TimeoutError"));
    }, timeoutMs);

    // If caller provided a signal, propagate its abort to our controller.
    if (options.signal) {
        if (options.signal.aborted) controller.abort(options.signal.reason);
        else options.signal.addEventListener("abort", () => controller.abort(options.signal!.reason), { once: true });
    }

    try {
        const response = await fetch(ENDPOINT, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({ text }),
            signal: controller.signal,
        });

        if (!response.ok) {
            let detail = "";
            try {
                const body = (await response.json()) as { detail?: unknown };
                if (typeof body.detail === "string") detail = `: ${body.detail}`;
                else if (Array.isArray(body.detail)) detail = `: ${JSON.stringify(body.detail)}`;
            } catch {
                // ignore JSON parse errors for error bodies
            }
            throw new Error(`Translation failed (${response.status})${detail}`);
        }

        const data: TranslateResponse = await response.json();
        return data.segments;
    } finally {
        clearTimeout(timeoutId);
    }
}
