import {
  useEventGates,
  useLiveScans,
  useTicketedEvents,
  useValidateScan,
  type ScanResult,
  type ScanVerdict,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  PageHeader,
  Select,
  StatCard,
} from "@footbola/ui";
import { Camera, CameraOff, ScanLine } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useI18n } from "../../app/locale";
import { useSession } from "../../app/session";

/**
 * The browser access-control demonstration.
 *
 * A stand-in for the Android application, not a replacement for it. It speaks
 * the same six endpoints the mobile client will, which is the point: by the
 * time somebody writes the Kotlin, the contract has been exercised by a real
 * user against a real database rather than only by tests.
 *
 * Three details are operational rather than cosmetic.
 *
 * **The verdict fills the screen.** A steward on a dark concourse with a queue
 * behind them reads a colour, not a sentence. Green admits, amber means the
 * ticket has already come in, red is everything else — and the amber case
 * shows *when and where* the first entry happened, because that is the first
 * thing the holder will argue about.
 *
 * **Every scan carries an idempotency key.** A dropped connection retried
 * without one turns a successful entry into ALREADY_USED against itself, and
 * the supporter who did nothing wrong gets turned away.
 *
 * **The camera is optional.** `BarcodeDetector` is not everywhere, and a
 * cracked phone screen does not scan at all, so typing a code by hand is a
 * first-class path rather than a fallback nobody tested.
 */

type DetectedBarcode = { rawValue: string };
type BarcodeDetectorLike = {
  detect: (source: CanvasImageSource) => Promise<DetectedBarcode[]>;
};
type BarcodeDetectorConstructor = new (options?: {
  formats?: string[];
}) => BarcodeDetectorLike;

/** Green admits, amber is a repeat, red is everything else. */
const TONE: Record<ScanResult, "success" | "warning" | "danger"> = {
  VALID: "success",
  ALREADY_USED: "warning",
  WRONG_GATE: "danger",
  WRONG_EVENT: "danger",
  NOT_YET_VALID: "danger",
  EXPIRED: "danger",
  CANCELLED: "danger",
  REFUNDED: "danger",
  DEVICE_REVOKED: "danger",
  UNKNOWN_CREDENTIAL: "danger",
};

const RESULT_KEY: Record<ScanResult, string> = {
  VALID: "resultValid",
  ALREADY_USED: "resultAlreadyUsed",
  WRONG_GATE: "resultWrongGate",
  WRONG_EVENT: "resultWrongEvent",
  NOT_YET_VALID: "resultNotYetValid",
  EXPIRED: "resultExpired",
  CANCELLED: "resultCancelled",
  REFUNDED: "resultRefunded",
  DEVICE_REVOKED: "resultDeviceRevoked",
  UNKNOWN_CREDENTIAL: "resultUnknown",
};

const SURFACE: Record<"success" | "warning" | "danger", string> = {
  success: "bg-emerald-600 text-white",
  warning: "bg-amber-500 text-white",
  danger: "bg-rose-600 text-white",
};

/**
 * A short tone and a buzz.
 *
 * Built from the Web Audio API rather than an audio file: it needs no asset,
 * no preload and no autoplay negotiation, and a steward needs a distinguishable
 * noise rather than a pleasant one.
 */
function feedback(tone: "success" | "warning" | "danger"): void {
  try {
    const Ctor =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (Ctor) {
      const context = new Ctor();
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.frequency.value = tone === "success" ? 880 : tone === "warning" ? 520 : 240;
      gain.gain.value = 0.06;
      oscillator.connect(gain).connect(context.destination);
      oscillator.start();
      oscillator.stop(context.currentTime + (tone === "success" ? 0.12 : 0.32));
      window.setTimeout(() => void context.close(), 600);
    }
  } catch {
    // A silent scanner still admits people. Never let audio break the queue.
  }

  if (typeof navigator.vibrate === "function") {
    navigator.vibrate(tone === "success" ? 60 : [80, 60, 80]);
  }
}

export function ScannerPage() {
  const { t } = useI18n();
  const { club } = useSession();

  const events = useTicketedEvents(club.id);
  const [eventId, setEventId] = useState<string>();
  const [gateCode, setGateCode] = useState<string>();
  const [manual, setManual] = useState("");
  const [verdict, setVerdict] = useState<ScanVerdict | null>(null);
  const [scanning, setScanning] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);

  const gates = useEventGates(eventId);
  const live = useLiveScans(eventId, { refetchInterval: scanning ? 3000 : 10000 });
  const validate = useValidateScan();

  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const loopRef = useRef<number | null>(null);
  // The last code seen, so holding a phone in front of the lens does not fire
  // twenty requests a second for the same ticket.
  const lastSeen = useRef<{ value: string; at: number } | null>(null);

  const published = useMemo(
    () => (events.data ?? []).filter((event) => event.status === "PUBLISHED"),
    [events.data],
  );

  useEffect(() => {
    const first = published[0];
    if (!eventId && first) setEventId(first.id);
  }, [published, eventId]);

  useEffect(() => {
    const first = gates.data?.[0];
    if (!gateCode && first) setGateCode(first.code);
  }, [gates.data, gateCode]);

  const submit = useCallback(
    async (credential: string) => {
      if (!eventId || !credential.trim()) return;
      try {
        const result = await validate.mutateAsync({
          event_id: eventId,
          credential: credential.trim(),
          gate_code: gateCode ?? null,
          // A retry after a timeout must return the verdict it already earned.
          idempotency_key: crypto.randomUUID(),
        });
        setVerdict(result);
        feedback(TONE[result.result]);
      } catch {
        setVerdict(null);
      }
    },
    [eventId, gateCode, validate],
  );

  const stopCamera = useCallback(() => {
    if (loopRef.current !== null) {
      window.clearInterval(loopRef.current);
      loopRef.current = null;
    }
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setScanning(false);
  }, []);

  const startCamera = useCallback(async () => {
    setCameraError(null);
    const Detector = (window as unknown as { BarcodeDetector?: BarcodeDetectorConstructor })
      .BarcodeDetector;

    if (!Detector || !navigator.mediaDevices?.getUserMedia) {
      setCameraError(t("ticketing", "cameraUnavailable"));
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play();
      }
      setScanning(true);

      const detector = new Detector({ formats: ["qr_code"] });
      loopRef.current = window.setInterval(() => {
        const video = videoRef.current;
        if (!video || video.readyState < 2) return;
        void detector
          .detect(video)
          .then((codes) => {
            const value = codes[0]?.rawValue;
            if (!value) return;
            const now = Date.now();
            // Same code within two seconds is the same phone still held up.
            if (lastSeen.current?.value === value && now - lastSeen.current.at < 2000) return;
            lastSeen.current = { value, at: now };
            void submit(value);
          })
          .catch(() => undefined);
      }, 300);
    } catch {
      setCameraError(t("ticketing", "cameraUnavailable"));
      stopCamera();
    }
  }, [stopCamera, submit, t]);

  useEffect(() => stopCamera, [stopCamera]);

  if (!published.length) {
    return (
      <div className="space-y-6">
        <PageHeader
          eyebrow={
            <>
              <ScanLine className="size-3.5" />
              {t("ticketing", "eyebrow")}
            </>
          }
          title={t("ticketing", "scannerTitle")}
          description={t("ticketing", "scannerDescription")}
        />
        <EmptyState
          title={t("ticketing", "noMatches")}
          description={t("ticketing", "noMatchesHint")}
        />
      </div>
    );
  }

  const tone = verdict ? TONE[verdict.result] : null;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={
          <>
            <ScanLine className="size-3.5" />
            {t("ticketing", "eyebrow")}
          </>
        }
        title={t("ticketing", "scannerTitle")}
        description={t("ticketing", "scannerDescription")}
        action={
          <div className="flex flex-wrap gap-2">
            <Select
              value={eventId ?? ""}
              onChange={setEventId}
              options={published.map((event) => ({ value: event.id, label: event.name }))}
            />
            <Select
              value={gateCode ?? ""}
              onChange={setGateCode}
              options={(gates.data ?? []).map((gate) => ({
                value: gate.code,
                label: `${t("ticketing", "gate")} ${gate.code}`,
              }))}
            />
          </div>
        }
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="space-y-4">
          {/* The verdict, big enough to read at arm's length in bad light. */}
          {verdict && tone ? (
            <Card className={`p-6 ${SURFACE[tone]}`} role="status" aria-live="assertive">
              <p className="text-3xl font-semibold tracking-tight">
                {t("ticketing", RESULT_KEY[verdict.result] as "resultValid")}
              </p>
              {verdict.seat && <p className="mt-2 text-lg opacity-95">{verdict.seat}</p>}
              <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm opacity-90">
                {verdict.ticket_number && <span>{verdict.ticket_number}</span>}
                {verdict.ticket_type && <span>{verdict.ticket_type}</span>}
                {verdict.holder_name && <span>{verdict.holder_name}</span>}
              </div>
              {verdict.result === "ALREADY_USED" && verdict.first_seen_at && (
                <p className="mt-3 rounded-lg bg-black/15 px-3 py-2 text-sm">
                  {t("ticketing", "firstSeen")}:{" "}
                  {new Date(verdict.first_seen_at).toLocaleTimeString()}
                  {verdict.first_seen_gate
                    ? ` · ${t("ticketing", "gate")} ${verdict.first_seen_gate}`
                    : ""}
                </p>
              )}
              <Button
                variant="secondary"
                className="mt-4"
                onClick={() => {
                  setVerdict(null);
                  setManual("");
                }}
              >
                {t("ticketing", "scanAgain")}
              </Button>
            </Card>
          ) : (
            <Card className="p-4">
              <div className="relative overflow-hidden rounded-xl bg-slate-900">
                <video
                  ref={videoRef}
                  className="aspect-video w-full object-cover"
                  muted
                  playsInline
                />
                {!scanning && (
                  <div className="absolute inset-0 grid place-items-center text-sm text-white/70">
                    {cameraError ?? t("ticketing", "startScanning")}
                  </div>
                )}
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-2">
                {scanning ? (
                  <Button variant="secondary" onClick={stopCamera}>
                    <CameraOff className="size-4" />
                    {t("ticketing", "stopScanning")}
                  </Button>
                ) : (
                  <Button variant="primary" onClick={() => void startCamera()}>
                    <Camera className="size-4" />
                    {t("ticketing", "startScanning")}
                  </Button>
                )}
              </div>

              <form
                className="mt-4 flex flex-wrap gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void submit(manual);
                }}
              >
                <Input
                  value={manual}
                  onChange={(event) => setManual(event.target.value)}
                  placeholder={t("ticketing", "manualEntry")}
                  aria-label={t("ticketing", "manualEntry")}
                  className="min-w-0 flex-1"
                />
                <Button
                  type="submit"
                  variant="primary"
                  loading={validate.isPending}
                  disabled={!manual.trim()}
                >
                  {t("ticketing", "scan")}
                </Button>
              </form>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <StatCard
              label={t("ticketing", "admitted")}
              value={(live.data?.admitted ?? 0).toLocaleString()}
            />
            <StatCard
              label={t("ticketing", "refused")}
              value={(live.data?.refused ?? 0).toLocaleString()}
            />
          </div>

          <Card className="p-4">
            <p className="text-sm font-medium text-text">{t("ticketing", "recentScans")}</p>
            {!live.data?.recent?.length ? (
              <p className="mt-3 text-sm text-text-tertiary">{t("ticketing", "noScans")}</p>
            ) : (
              <ul className="mt-3 divide-y divide-border">
                {live.data.recent.map((scan) => (
                  <li key={scan.id} className="flex items-center gap-2 py-2 text-sm">
                    <Badge
                      tone={
                        scan.result === "VALID"
                          ? "success"
                          : scan.result === "ALREADY_USED"
                            ? "warning"
                            : "danger"
                      }
                      size="sm"
                    >
                      {scan.result}
                    </Badge>
                    <span className="truncate text-xs text-text-secondary">
                      {scan.seat ?? "—"}
                    </span>
                    <span className="ml-auto text-xs text-text-tertiary" data-numeric>
                      {new Date(scan.server_at).toLocaleTimeString()}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
