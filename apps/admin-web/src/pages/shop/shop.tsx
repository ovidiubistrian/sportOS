import {
  useProducts,
  useSetOrderStatus,
  useShopOrders,
  type Product,
  type ShopOrder,
} from "@footbola/api-client";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  PageHeader,
  Section,
  Skeleton,
  cn,
} from "@footbola/ui";
import { Package, Plus, ShoppingBag } from "lucide-react";
import { useState } from "react";

import { useI18n } from "../../app/locale";
import { useSession } from "../../app/session";
import { formatMoney } from "./money";
import { ProductEditor } from "./product-editor";

/**
 * The club shop.
 *
 * Products and orders on one page, in that order, because the club's two
 * questions are "what am I selling" and "who is waiting at the counter" — and
 * the second is answered by a reference number somebody is reading aloud, so it
 * needs to be findable without a search.
 */

function stockLabel(product: Product, t: ReturnType<typeof useI18n>["t"]): string | null {
  const total = product.variants.reduce((sum, variant) => sum + variant.stock, 0);
  if (total === 0) return t("shop", "soldOut");
  if (total <= 5) return t("shop", "lowStock", { count: total });
  return null;
}

function ProductCard({ product, onEdit }: { product: Product; onEdit: () => void }) {
  const { t, locale } = useI18n();
  const low = stockLabel(product, t);

  return (
    <Card interactive className="overflow-hidden" onClick={onEdit}>
      <div className="aspect-square bg-bg-muted">
        {product.cover_url ? (
          <img
            src={product.cover_url}
            alt=""
            className="h-full w-full object-cover"
          />
        ) : (
          <span className="grid h-full place-items-center text-text-tertiary">
            <Package className="size-8" />
          </span>
        )}
      </div>
      <div className="p-3.5">
        <div className="flex items-start justify-between gap-2">
          <p className="truncate text-sm font-medium text-text">{product.name}</p>
          {!product.is_active && <Badge tone="neutral">{t("common", "hidden")}</Badge>}
        </div>
        <p className="mt-1 text-sm tabular-nums text-text-secondary">
          {formatMoney(product.price_minor, product.currency, locale)}
        </p>
        <p className="mt-2 flex flex-wrap gap-1">
          {product.variants.map((variant) => (
            <span
              key={variant.id}
              className={cn(
                "rounded px-1.5 py-0.5 text-[11px] tabular-nums",
                variant.stock === 0
                  ? "bg-danger-bg text-danger"
                  : "bg-bg-muted text-text-secondary",
              )}
            >
              {variant.label} · {variant.stock}
            </span>
          ))}
        </p>
        {low && (
          <p className="mt-2 text-xs font-medium text-warning">{low}</p>
        )}
      </div>
    </Card>
  );
}

function OrderRow({ order, clubId }: { order: ShopOrder; clubId: string }) {
  const { t, locale, formatDate } = useI18n();
  const act = useSetOrderStatus(clubId);
  const open = order.status === "AWAITING_COLLECTION";

  return (
    <li className="grid items-center gap-3 border-b border-border py-3 last:border-0 sm:grid-cols-[7rem_1fr_auto]">
      <p className="font-mono text-sm font-semibold tracking-wider text-text">
        {order.reference}
      </p>

      <div className="min-w-0">
        <p className="truncate text-sm text-text">{order.buyer_name}</p>
        <p className="mt-0.5 truncate text-xs text-text-tertiary">
          {order.lines.map((line) => `${line.quantity}× ${line.description}`).join(", ")}
        </p>
      </div>

      <div className="flex items-center gap-3 sm:justify-end">
        <span className="text-sm font-semibold tabular-nums text-text">
          {formatMoney(order.total_minor, order.currency, locale)}
        </span>
        {order.placed_at && (
          <span className="hidden text-xs text-text-tertiary lg:inline">
            {formatDate(order.placed_at)}
          </span>
        )}
        {open ? (
          <>
            <Button
              size="sm"
              loading={act.isPending}
              onClick={() => act.mutate({ id: order.id, status: "COLLECTED" })}
            >
              {t("shop", "collect")}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => act.mutate({ id: order.id, status: "CANCELLED" })}
            >
              {t("shop", "cancel")}
            </Button>
          </>
        ) : (
          <Badge tone={order.status === "COLLECTED" ? "success" : "neutral"}>
            {t("shop", `status${order.status}` as "statusCOLLECTED")}
          </Badge>
        )}
      </div>
    </li>
  );
}

export function ShopPage() {
  const { club, can } = useSession();
  const { t } = useI18n();
  const canManage = can("commerce.product.manage");

  const products = useProducts(club.id);
  const orders = useShopOrders(club.id);

  const [editing, setEditing] = useState<Product | null | undefined>(undefined);

  if (products.isError) {
    return (
      <ErrorState
        error={products.error}
        onRetry={() => void products.refetch()}
        title={t("common", "somethingWentWrong")}
        retryLabel={t("common", "tryAgain")}
      />
    );
  }

  // The club's currency comes off a product; before the first one there is
  // nothing to read it from, so the club's own is the sensible default.
  const currency = products.data?.[0]?.currency ?? "EUR";
  const waiting = (orders.data ?? []).filter(
    (order) => order.status === "AWAITING_COLLECTION",
  );

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow={
          <>
            <ShoppingBag className="size-3.5" />
            {t("shop", "eyebrow")}
          </>
        }
        title={t("shop", "title")}
        description={t("shop", "description")}
        action={
          canManage && (
            <Button onClick={() => setEditing(null)}>
              <Plus className="size-4" />
              {t("shop", "add")}
            </Button>
          )
        }
      />

      <Section title={t("shop", "products")} description={t("shop", "productsHint")}>
        {products.isLoading ? (
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {Array.from({ length: 5 }).map((_, index) => (
              <Skeleton key={index} className="h-64" />
            ))}
          </div>
        ) : (products.data ?? []).length === 0 ? (
          <EmptyState
            icon={<Package />}
            title={t("shop", "noProducts")}
            description={t("shop", "noProductsBody")}
            action={
              canManage && (
                <Button onClick={() => setEditing(null)}>{t("shop", "add")}</Button>
              )
            }
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {(products.data ?? []).map((product) => (
              <ProductCard
                key={product.id}
                product={product}
                onEdit={() => canManage && setEditing(product)}
              />
            ))}
          </div>
        )}
      </Section>

      <Section
        title={t("shop", "orders")}
        description={t("shop", "ordersHint")}
        action={
          waiting.length > 0 && (
            <Badge tone="warning">{waiting.length}</Badge>
          )
        }
      >
        {orders.isLoading ? (
          <Skeleton className="h-32" />
        ) : (orders.data ?? []).length === 0 ? (
          <EmptyState
            icon={<ShoppingBag />}
            title={t("shop", "noOrders")}
            description={t("shop", "noOrdersBody")}
          />
        ) : (
          <Card className="px-4">
            <ul>
              {(orders.data ?? []).map((order) => (
                <OrderRow key={order.id} order={order} clubId={club.id} />
              ))}
            </ul>
          </Card>
        )}
      </Section>

      <ProductEditor
        open={editing !== undefined}
        onOpenChange={(open) => !open && setEditing(undefined)}
        product={editing ?? null}
        currency={currency}
      />
    </div>
  );
}
