import {
  ApiError,
  useDeleteMedia,
  useMedia,
  useSetAltText,
  useUploadMedia,
  type MediaAsset,
  type MediaPurpose,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  Input,
  Skeleton,
  Spinner,
  cn,
  useToast,
} from "@footbola/ui";
import { AlertTriangle, ImagePlus, Trash2, Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

import { useI18n } from "../../app/locale";
import { useSession } from "../../app/session";

/**
 * Picking an image for one job.
 *
 * The uploader and the library are the same control: a club that has already
 * uploaded three crests should reuse one, not upload a fourth. Separating
 * "upload" from "choose" is how media libraries fill up with near-duplicates
 * nobody dares delete.
 *
 * Alt text is required here rather than optional. Everything this component
 * handles ends up on the club's public website, where an image without a
 * description is invisible to a screen reader and to search — and asking for it
 * at upload, while the person still remembers what the picture shows, is the
 * only moment they will actually write a useful one.
 */

const MAX_MB = 8;
const ACCEPT = "image/png,image/jpeg,image/webp";

function humanSize(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.round(bytes / 1024)} KB`
    : `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function Preview({
  asset,
  selected,
  onSelect,
  onDelete,
  deleting,
}: {
  asset: MediaAsset;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
  deleting: boolean;
}) {
  return (
    <div className="group relative">
      <button
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className={cn(
          "block w-full overflow-hidden rounded-md border bg-bg-muted transition-all",
          selected
            ? "border-brand ring-1 ring-brand"
            : "border-border hover:border-border-strong",
        )}
      >
        <span className="grid aspect-[3/2] place-items-center p-2">
          <img
            src={asset.url}
            alt={asset.alt_text ?? ""}
            loading="lazy"
            width={asset.width}
            height={asset.height}
            className="max-h-full max-w-full object-contain"
          />
        </span>
      </button>

      {!asset.alt_text && (
        <span
          className="absolute top-1.5 left-1.5 grid size-5 place-items-center rounded-full bg-warning-bg text-warning"
          title="This image has no description"
        >
          <AlertTriangle className="size-3" />
        </span>
      )}

      <Button
        variant="secondary"
        size="icon-sm"
        aria-label="Delete image"
        loading={deleting}
        onClick={onDelete}
        className="absolute top-1.5 right-1.5 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
      >
        <Trash2 />
      </Button>
    </div>
  );
}

export function ImageField({
  purpose,
  label,
  help,
  value,
  onChange,
  aspect = "3/2",
}: {
  purpose: MediaPurpose;
  label: string;
  help?: string;
  /** The chosen asset's URL, or null. */
  value: string | null;
  onChange: (asset: MediaAsset | null) => void;
  aspect?: string;
}) {
  const { club, can } = useSession();
  const { t } = useI18n();
  const toast = useToast();

  const library = useMedia(club.id, purpose);
  const upload = useUploadMedia();
  const remove = useDeleteMedia();
  const setAlt = useSetAltText();

  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [pendingAlt, setPendingAlt] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const editable = can("clubs.club.update");
  const assets = library.data ?? [];
  const selected = assets.find((asset) => asset.url === value) ?? null;

  const accept = (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_MB * 1024 * 1024) {
      // Refused here as well as on the server: the point of the client check is
      // to save an eight-megabyte round trip, not to be the guard.
      toast.error(`That image is larger than ${MAX_MB} MB.`);
      return;
    }
    upload.mutate(
      { clubId: club.id, purpose, file, altText: pendingAlt.trim() || undefined },
      {
        onSuccess: (asset) => {
          setPendingAlt("");
          onChange(asset);
        },
        onError: (error: ApiError) =>
          toast.error(t("site", "couldNotSave"), error.message),
      },
    );
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (editable) accept(event.dataTransfer.files[0]);
  };

  return (
    <div className="space-y-2.5">
      <div>
        <p className="text-sm font-medium text-text">{label}</p>
        {help && <p className="mt-0.5 text-xs text-text-secondary">{help}</p>}
      </div>

      {/* The current choice, at the aspect ratio the site will render it in, so
          a crest that will be cropped is visibly cropped here first. */}
      <Card className="overflow-hidden">
        <div
          className="grid place-items-center bg-bg-muted p-4"
          style={{ aspectRatio: aspect }}
        >
          {selected ? (
            <img
              src={selected.url}
              alt={selected.alt_text ?? ""}
              className="max-h-full max-w-full object-contain"
            />
          ) : (
            <span className="flex flex-col items-center gap-1.5 text-text-tertiary">
              <ImagePlus className="size-6" />
              <span className="text-xs">Nothing chosen</span>
            </span>
          )}
        </div>

        {selected && (
          <div className="flex flex-wrap items-center gap-2 border-t border-border p-2.5">
            <Input
              value={selected.alt_text ?? ""}
              disabled={!editable}
              placeholder="Describe the picture"
              aria-label="Image description"
              className="min-w-40 flex-1"
              onChange={(event) =>
                setAlt.mutate({ assetId: selected.id, altText: event.target.value })
              }
            />
            <span className="text-xs text-text-tertiary" data-numeric>
              {selected.width}×{selected.height} · {humanSize(selected.size_bytes)}
            </span>
            <Button variant="ghost" size="sm" onClick={() => onChange(null)}>
              {t("common", "clear")}
            </Button>
          </div>
        )}
      </Card>

      {editable && (
        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cn(
            "rounded-md border border-dashed p-3 transition-colors",
            dragging ? "border-brand bg-brand-subtle" : "border-border",
          )}
        >
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              loading={upload.isPending}
              onClick={() => inputRef.current?.click()}
            >
              <Upload />
              Upload
            </Button>
            <Input
              value={pendingAlt}
              placeholder="Describe the picture (used by screen readers)"
              aria-label="Description for the next upload"
              className="min-w-48 flex-1"
              onChange={(event) => setPendingAlt(event.target.value)}
            />
          </div>
          <p className="mt-1.5 text-xs text-text-tertiary">
            PNG, JPEG or WebP, up to {MAX_MB} MB. Drop a file anywhere in this box.
          </p>

          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            hidden
            onChange={(event) => {
              accept(event.target.files?.[0]);
              // Clearing lets the same file be chosen twice in a row, which
              // otherwise silently does nothing.
              event.target.value = "";
            }}
          />
        </div>
      )}

      {library.isLoading ? (
        <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
          {[0, 1, 2, 3].map((index) => (
            <Skeleton key={index} className="aspect-[3/2]" />
          ))}
        </div>
      ) : (
        assets.length > 0 && (
          <>
            <p className="flex items-center gap-2 text-xs text-text-tertiary">
              Already uploaded
              <Badge tone="outline">{assets.length}</Badge>
              {upload.isPending && <Spinner className="size-3" />}
            </p>
            <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
              {assets.map((asset) => (
                <Preview
                  key={asset.id}
                  asset={asset}
                  selected={asset.url === value}
                  deleting={deletingId === asset.id}
                  onSelect={() => onChange(asset)}
                  onDelete={() => {
                    setDeletingId(asset.id);
                    remove.mutate(
                      { assetId: asset.id, clubId: club.id },
                      {
                        onSettled: () => setDeletingId(null),
                        onSuccess: () => {
                          if (asset.url === value) onChange(null);
                        },
                        onError: (error: ApiError) =>
                          toast.error(t("site", "couldNotSave"), error.message),
                      },
                    );
                  }}
                />
              ))}
            </div>
          </>
        )
      )}
    </div>
  );
}
