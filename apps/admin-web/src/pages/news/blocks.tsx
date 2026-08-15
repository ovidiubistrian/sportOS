import type { Block } from "@footbola/api-client";
import { Badge, Button, Input, Textarea, cn } from "@footbola/ui";

import { useI18n } from "../../app/locale";
import { ArrowDown, ArrowUp, Plus, Trash2, X } from "lucide-react";

/**
 * The body editor.
 *
 * A list of typed blocks, not a rich-text field. An editor writing a club
 * announcement needs a paragraph, a subheading, a quote and a list — and
 * nothing that can produce markup, because the four public templates render
 * these blocks as text nodes in their own style.
 */

/** Catalogue keys, resolved by the caller — the block model is not localised. */
export const BLOCK_LABEL_KEYS = {
  paragraph: "paragraph",
  heading: "heading",
  quote: "quote",
  list: "list",
} as const;

export function emptyBlock(type: Block["type"]): Block {
  switch (type) {
    case "heading":
      return { type: "heading", level: 2, text: "" };
    case "quote":
      return { type: "quote", text: "", attribution: "" };
    case "list":
      return { type: "list", ordered: false, items: [""] };
    default:
      return { type: "paragraph", text: "" };
  }
}

/** Empty blocks are dropped on save rather than rejected mid-typing. */
export function pruneBlocks(blocks: Block[]): Block[] {
  return blocks
    .map((block) =>
      block.type === "list"
        ? { ...block, items: block.items.map((i) => i.trim()).filter(Boolean) }
        : block,
    )
    .filter((block) =>
      block.type === "list" ? block.items.length > 0 : block.text.trim().length > 0,
    );
}

export function blockText(block: Block): string {
  return block.type === "list" ? block.items.join("\n") : block.text;
}

function AutoTextarea({
  value,
  onChange,
  placeholder,
  rows = 3,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  label: string;
}) {
  return (
    <Textarea
      aria-label={label}
      value={value}
      rows={rows}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function BlockBody({
  block,
  onChange,
}: {
  block: Block;
  onChange: (block: Block) => void;
}) {
  const { t } = useI18n();
  switch (block.type) {
    case "heading":
      return (
        <div className="flex gap-2">
          <select
            aria-label={t("blocks", "heading")}
            value={block.level}
            onChange={(event) =>
              onChange({ ...block, level: Number(event.target.value) as 2 | 3 })
            }
            className="h-8 shrink-0 rounded-sm border border-border bg-surface px-2 text-sm text-text"
          >
            <option value={2}>H2</option>
            <option value={3}>H3</option>
          </select>
          <Input
            aria-label={t("blocks", "heading")}
            value={block.text}
            placeholder={t("blocks", "sectionTitle")}
            onChange={(event) => onChange({ ...block, text: event.target.value })}
          />
        </div>
      );

    case "quote":
      return (
        <div className="space-y-2">
          <AutoTextarea
            label={t("blocks", "quote")}
            value={block.text}
            placeholder={t("blocks", "quotePlaceholder")}
            onChange={(text) => onChange({ ...block, text })}
          />
          <Input
            aria-label={t("blocks", "attributionPlaceholder")}
            value={block.attribution ?? ""}
            placeholder={t("blocks", "attributionPlaceholder")}
            onChange={(event) => onChange({ ...block, attribution: event.target.value })}
          />
        </div>
      );

    case "list":
      return (
        <div className="space-y-2">
          <select
            aria-label={t("blocks", "list")}
            value={block.ordered ? "number" : "bullet"}
            onChange={(event) =>
              onChange({ ...block, ordered: event.target.value === "number" })
            }
            className="h-8 rounded-sm border border-border bg-surface px-2 text-sm text-text"
          >
            <option value="bullet">{t("blocks", "bulleted")}</option>
            <option value="number">{t("blocks", "numbered")}</option>
          </select>
          {block.items.map((item, index) => (
            <div key={index} className="flex gap-2">
              <Input
                aria-label={`List item ${index + 1}`}
                value={item}
                onChange={(event) => {
                  const items = [...block.items];
                  items[index] = event.target.value;
                  onChange({ ...block, items });
                }}
              />
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={`Remove item ${index + 1}`}
                onClick={() =>
                  onChange({
                    ...block,
                    items: block.items.filter((_, i) => i !== index),
                  })
                }
              >
                <X />
              </Button>
            </div>
          ))}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onChange({ ...block, items: [...block.items, ""] })}
          >
            <Plus />
            {t("blocks", "addItem")}
          </Button>
        </div>
      );

    default:
      return (
        <AutoTextarea
          label={t("blocks", "paragraph")}
          value={block.text}
          rows={4}
          placeholder={t("blocks", "paragraphPlaceholder")}
          onChange={(text) => onChange({ ...block, text })}
        />
      );
  }
}

export function BlockEditor({
  blocks,
  onChange,
  disabled,
}: {
  blocks: Block[];
  onChange: (blocks: Block[]) => void;
  disabled?: boolean;
}) {
  const { t } = useI18n();

  const replace = (index: number, block: Block) =>
    onChange(blocks.map((existing, i) => (i === index ? block : existing)));

  const move = (index: number, delta: number) => {
    const target = index + delta;
    const moving = blocks[index];
    const displaced = blocks[target];
    if (!moving || !displaced) return;
    const next = [...blocks];
    next[index] = displaced;
    next[target] = moving;
    onChange(next);
  };

  return (
    <fieldset disabled={disabled} className="space-y-3">
      {blocks.map((block, index) => (
        <div
          key={index}
          className="rounded-lg border border-border bg-surface p-3 transition-colors hover:border-border-strong"
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <Badge>{t("blocks", BLOCK_LABEL_KEYS[block.type])}</Badge>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("blocks", "moveUp")}
                disabled={index === 0}
                onClick={() => move(index, -1)}
              >
                <ArrowUp />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("blocks", "moveDown")}
                disabled={index === blocks.length - 1}
                onClick={() => move(index, 1)}
              >
                <ArrowDown />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("blocks", "removeBlock")}
                onClick={() => onChange(blocks.filter((_, i) => i !== index))}
              >
                <Trash2 />
              </Button>
            </div>
          </div>
          <BlockBody block={block} onChange={(next) => replace(index, next)} />
        </div>
      ))}

      <div className="flex flex-wrap gap-2">
        {(Object.keys(BLOCK_LABEL_KEYS) as Block["type"][]).map((type) => (
          <Button
            key={type}
            variant="secondary"
            size="sm"
            onClick={() => onChange([...blocks, emptyBlock(type)])}
          >
            <Plus />
            {t("blocks", BLOCK_LABEL_KEYS[type])}
          </Button>
        ))}
      </div>
    </fieldset>
  );
}

/** Read-only rendering, used by the assistant's side-by-side comparison. */
export function BlockPreview({
  blocks,
  changed,
}: {
  blocks: Block[];
  /** Indices whose text differs from the other side. */
  changed?: Set<number>;
}) {
  if (blocks.length === 0) {
    return <p className="p-3 text-sm text-text-tertiary">—</p>;
  }
  return (
    <div className="space-y-2 p-3">
      {blocks.map((block, index) => (
        <div
          key={index}
          className={cn(
            "rounded-sm px-2 py-1.5 text-sm",
            changed?.has(index) ? "bg-warning-bg text-text" : "text-text-secondary",
          )}
        >
          {block.type === "heading" && (
            <strong className="text-text">{block.text}</strong>
          )}
          {block.type === "paragraph" && <span>{block.text}</span>}
          {block.type === "quote" && (
            <blockquote className="border-l-2 border-border pl-2 italic">
              {block.text}
              {block.attribution && (
                <footer className="mt-1 text-xs not-italic text-text-tertiary">
                  — {block.attribution}
                </footer>
              )}
            </blockquote>
          )}
          {block.type === "list" &&
            (block.ordered ? (
              <ol className="list-inside list-decimal">
                {block.items.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ol>
            ) : (
              <ul className="list-inside list-disc">
                {block.items.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
            ))}
        </div>
      ))}
    </div>
  );
}
