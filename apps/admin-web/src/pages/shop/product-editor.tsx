import {
  useCreateProduct,
  useDeleteProduct,
  useUpdateProduct,
  type Product,
  type VariantInput,
} from "@footbola/api-client";
import {
  Button,
  Dialog,
  Field,
  Input,
  Switch,
  Textarea,
  useToast,
} from "@footbola/ui";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../app/locale";
import { useSession } from "../../app/session";
import { ImageField } from "../site/image-field";
import { minorToInput, parsePrice } from "./money";

/**
 * Adding and editing a product.
 *
 * Sizes are rows rather than a text field because each one carries its own
 * stock, and stock is the number that decides whether a supporter can buy. A
 * product without sizes still gets one row — the server names it "One size" if
 * the club leaves the list empty — so nothing downstream has to handle a
 * product that has stock in two different places.
 */
export function ProductEditor({
  open,
  onOpenChange,
  product,
  currency,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Null to create. */
  product: Product | null;
  currency: string;
}) {
  const { t } = useI18n();
  const { club } = useSession();
  const toast = useToast();
  const create = useCreateProduct();
  const update = useUpdateProduct();
  const remove = useDeleteProduct();

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [price, setPrice] = useState("");
  const [coverId, setCoverId] = useState<string | null>(null);
  const [coverUrl, setCoverUrl] = useState<string | null>(null);
  const [isActive, setIsActive] = useState(true);
  const [variants, setVariants] = useState<VariantInput[]>([]);
  const [seeded, setSeeded] = useState<string | null>(null);

  const key = product?.id ?? (open ? "new" : null);
  if (key && seeded !== key) {
    setSeeded(key);
    setName(product?.name ?? "");
    setDescription(product?.description ?? "");
    setPrice(product ? minorToInput(product.price_minor, currency) : "");
    setCoverId(product?.cover_media_id ?? null);
    setCoverUrl(product?.cover_url ?? null);
    setIsActive(product?.is_active ?? true);
    setVariants(
      product?.variants.map((v) => ({
        id: v.id,
        label: v.label,
        sku: v.sku,
        stock: v.stock,
      })) ?? [{ label: "", stock: 0 }],
    );
  }
  if (!open && seeded !== null) setSeeded(null);

  const busy = create.isPending || update.isPending || remove.isPending;
  const priceMinor = parsePrice(price, currency);

  function submit() {
    const fields = {
      name: name.trim(),
      description: description.trim() || null,
      price_minor: priceMinor ?? 0,
      cover_media_id: coverId,
      is_active: isActive,
      // A row left blank is someone who started typing and changed their mind,
      // not a size called "".
      variants: variants
        .filter((v) => v.label.trim())
        .map((v, index) => ({ ...v, label: v.label.trim(), sort_order: index })),
    };
    const done = {
      onSuccess: () => {
        toast.success(t("shop", product ? "updated" : "created"));
        onOpenChange(false);
      },
      onError: (error: Error) => toast.error(error.message),
    };

    if (product) update.mutate({ id: product.id, changes: fields }, done);
    else create.mutate({ club_id: club.id, ...fields }, done);
  }

  function setVariant(index: number, patch: Partial<VariantInput>) {
    setVariants((rows) =>
      rows.map((row, position) => (position === index ? { ...row, ...patch } : row)),
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("shop", product ? "editTitle" : "addTitle")}
      size="lg"
      footer={
        <>
          {product && (
            <Button
              variant="ghost"
              className="mr-auto text-danger"
              disabled={busy}
              onClick={() => {
                if (!window.confirm(t("shop", "removeConfirm"))) return;
                remove.mutate(product.id, {
                  onSuccess: () => {
                    toast.success(t("shop", "deleted"));
                    onOpenChange(false);
                  },
                  onError: (error) => toast.error(error.message),
                });
              }}
            >
              <Trash2 className="size-4" />
              {t("shop", "remove")}
            </Button>
          )}
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("common", "cancel")}
          </Button>
          <Button
            onClick={submit}
            loading={busy}
            disabled={!name.trim() || priceMinor === null}
          >
            {t("common", "save")}
          </Button>
        </>
      }
    >
      <div className="grid gap-5 sm:grid-cols-[1fr_13rem]">
        <div className="space-y-4">
          <Field label={t("shop", "name")} required>
            {(props) => (
              <Input
                {...props}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Fular"
              />
            )}
          </Field>

          <Field label={t("shop", "price")} required>
            {(props) => (
              <div className="flex items-center gap-2">
                <Input
                  {...props}
                  value={price}
                  onChange={(event) => setPrice(event.target.value)}
                  inputMode="decimal"
                  placeholder="0.00"
                  className="tabular-nums"
                />
                <span className="text-sm text-text-secondary">{currency}</span>
              </div>
            )}
          </Field>

          <Field
            label={t("shop", "productDescription")}
            help={t("shop", "descriptionHint")}
          >
            {(props) => (
              <Textarea
                {...props}
                rows={3}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            )}
          </Field>
        </div>

        <div className="space-y-4">
          <ImageField
            purpose="ARTICLE_IMAGE"
            label={t("shop", "image")}
            help={t("shop", "imageHint")}
            value={coverUrl}
            aspect="1/1"
            onChange={(asset) => {
              setCoverId(asset?.id ?? null);
              setCoverUrl(asset?.url ?? null);
            }}
          />
          <div>
            <label className="flex items-center gap-2.5 text-sm text-text">
              <Switch
                checked={isActive}
                onChange={setIsActive}
                label={t("shop", "visible")}
              />
              {t("shop", "visible")}
            </label>
            <p className="mt-1 text-xs text-text-secondary">{t("shop", "visibleHint")}</p>
          </div>
        </div>

        <div className="sm:col-span-2">
          <p className="text-sm font-medium text-text">{t("shop", "sizes")}</p>
          <p className="mt-0.5 mb-3 text-xs text-text-secondary">{t("shop", "sizesHint")}</p>

          <div className="space-y-2">
            {variants.map((variant, index) => (
              <div
                key={variant.id ?? `new-${index}`}
                className="grid grid-cols-[1fr_1fr_6rem_auto] items-center gap-2"
              >
                <Input
                  value={variant.label}
                  aria-label={t("shop", "sizeLabel")}
                  placeholder={t("shop", "sizeLabel")}
                  onChange={(event) => setVariant(index, { label: event.target.value })}
                />
                <Input
                  value={variant.sku ?? ""}
                  aria-label={t("shop", "sku")}
                  placeholder={t("shop", "sku")}
                  onChange={(event) => setVariant(index, { sku: event.target.value })}
                />
                <Input
                  type="number"
                  min={0}
                  value={variant.stock}
                  aria-label={t("shop", "stock")}
                  className="tabular-nums"
                  onChange={(event) =>
                    setVariant(index, { stock: Number(event.target.value) || 0 })
                  }
                />
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={t("shop", "remove")}
                  onClick={() =>
                    setVariants((rows) => rows.filter((_, position) => position !== index))
                  }
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            ))}
          </div>

          <Button
            variant="ghost"
            size="sm"
            className="mt-2"
            onClick={() => setVariants((rows) => [...rows, { label: "", stock: 0 }])}
          >
            <Plus className="size-4" />
            {t("shop", "addSize")}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
