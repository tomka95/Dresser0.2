'use client';

/**
 * /closet/[id] — item detail (§3 · C2). Hero image, editable field rows with
 * per-field confidence dots, source line, favourite, ⋮ context menu, save.
 *
 * REAL: GET /closet/{id} + PATCH /closet/{id} (name/brand/category/color/size/
 * unitPrice), favourite (persisted, optimistic). HONEST: per-field confidence is
 * read from item.analysisRaw when present and otherwise defaults to CONFIRMED
 * (mint) — never faked low, never hardcoded all-confirmed; quantity + order date
 * are read-only (PATCH won't accept them); "Mark as returned" / "Delete item"
 * have no backend, so they stay in the menu but surface an honest "not available
 * yet" toast rather than pretending to succeed.
 */

import React, { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Heart, MoreVertical, Pencil, Link2, ExternalLink, Undo2, Trash2, Mail } from 'lucide-react';
import { useClosetStore } from '@/stores/useClosetStore';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useToastStore } from '@/stores/useToastStore';
import { AppShell } from '@/components/layout/AppShell';
import { ItemImage } from '@/components/ui/ItemImage';
import { ConfidenceDot } from '@/components/ui/ConfidenceDot';
import {
  Btn,
  ContextMenu,
  GlassCard,
  Icon,
  RadioRow,
  RoundBtn,
  Sheet,
  SkDetail,
  Spark,
  TopBar,
  M,
  NAV_CLEAR,
} from '@/components/ds';
import type { ClosetItem, ClosetItemUpdate } from '@tailor/contracts';
import { logEvent } from '@/lib/api/events';

interface ItemDetailsPageProps {
  params: {
    id: string;
  };
}

const CATEGORY_OPTIONS = ['top', 'bottom', 'dress', 'outerwear', 'shoes', 'accessories', 'other'] as const;
type Category = (typeof CATEGORY_OPTIONS)[number];

const CATEGORY_LABELS: Record<Category, string> = {
  top: 'Top',
  bottom: 'Bottom',
  dress: 'Dress',
  outerwear: 'Outerwear',
  shoes: 'Shoes',
  accessories: 'Accessories',
  other: 'Other',
};

/** Editable text fields managed by the form (all PATCHable). */
type EditableField = 'name' | 'brand' | 'color' | 'size' | 'unitPrice';

/**
 * Per-field confidence — the backend has no field-level scores on closet items
 * yet, so this reads whatever real signal the item carries and otherwise returns
 * CONFIRMED (1). If analysis_raw ever ships a `fieldConfidence`/`confidence` map
 * (keyed by field), we honour it verbatim; a numeric 0..1 renders the amber
 * low-confidence cue below 0.7. Nothing is hardcoded low, nothing is forced high.
 */
function readFieldConfidence(item: ClosetItem | null): Record<string, number> {
  const raw = item?.analysisRaw;
  if (raw && typeof raw === 'object') {
    const map =
      (raw as Record<string, unknown>).fieldConfidence ??
      (raw as Record<string, unknown>).field_confidence ??
      (raw as Record<string, unknown>).confidence;
    if (map && typeof map === 'object') {
      const out: Record<string, number> = {};
      for (const [k, v] of Object.entries(map as Record<string, unknown>)) {
        if (typeof v === 'number' && Number.isFinite(v)) out[k] = v;
      }
      return out;
    }
  }
  return {};
}

export default function ItemDetailsPage({ params }: ItemDetailsPageProps) {
  const router = useRouter();
  const { id } = params;
  const pushToast = useToastStore((s) => s.toast);

  // Stable `status` boolean for effect deps — a background token refresh must not
  // re-run the seed effect and clobber edits.
  const { status } = useRequireAuth();
  const isAuthed = status === 'authenticated';

  const fetchItem = useClosetStore((state) => state.fetchItem);
  const updateItem = useClosetStore((state) => state.updateItem);
  const isItemLoading = useClosetStore((state) => state.isItemLoading[id]);
  const error = useClosetStore((state) => state.error);

  // Form state
  const [form, setForm] = useState<Record<EditableField, string>>({
    name: '',
    brand: '',
    color: '',
    size: '',
    unitPrice: '',
  });
  const [category, setCategory] = useState<Category>('other');
  const [imageUrl, setImageUrl] = useState<string | undefined>(undefined);
  const [merchant, setMerchant] = useState<string | undefined>(undefined);
  const [quantity, setQuantity] = useState<number | undefined>(undefined);
  const [orderDate, setOrderDate] = useState<string | undefined>(undefined);
  const [currency, setCurrency] = useState<string | undefined>(undefined);
  const [fieldConf, setFieldConf] = useState<Record<string, number>>({});
  const [loadedOnce, setLoadedOnce] = useState(false);

  const [editingField, setEditingField] = useState<EditableField | null>(null);
  const [categoryPickerOpen, setCategoryPickerOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [faved, setFaved] = useState(false); // seeded from item.isFavorite; persisted on toggle

  const [isSaving, setIsSaving] = useState(false);

  // Seed once authenticated.
  useEffect(() => {
    if (!isAuthed) return;
    fetchItem(id)
      .then((item) => {
        setForm({
          name: item.name,
          brand: item.brand ?? '',
          color: item.color ?? '',
          size: item.size ?? '',
          unitPrice: item.unitPrice != null ? String(item.unitPrice) : '',
        });
        setCategory((item.category as Category) ?? 'other');
        setImageUrl(item.imageUrl);
        setMerchant(item.merchant);
        setQuantity(item.quantity);
        setOrderDate(item.orderDate);
        setCurrency(item.currency);
        setFaved(!!item.isFavorite); // seed from the persisted flag
        setFieldConf(readFieldConfidence(item)); // real per-field scores if any
        setLoadedOnce(true);
      })
      .catch(() => {
        // Error handled by store, component shows error view
      });
  }, [id, fetchItem, isAuthed]);

  // Detail open -> `expand` (once per mount for this item).
  useEffect(() => {
    if (isAuthed) logEvent({ eventType: 'expand', itemId: id, source: 'closet_detail' });
  }, [id, isAuthed]);

  const currencySymbol = currency === 'GBP' ? '£' : currency === 'EUR' ? '€' : '$';
  const fromGmail = !!merchant; // receipts carry a merchant; Gmail is our receipt source

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const updates: ClosetItemUpdate = {
        name: form.name.trim(),
        category,
        eventSource: 'closet_detail',
      };
      if (form.brand.trim()) updates.brand = form.brand.trim();
      if (form.color.trim()) updates.color = form.color.trim();
      if (form.size.trim()) updates.size = form.size.trim();
      const price = Number(form.unitPrice);
      if (form.unitPrice.trim() && Number.isFinite(price)) updates.unitPrice = price;

      await updateItem(id, updates);
      setEditingField(null);
      pushToast({ tone: 'success', title: 'Changes saved' });
    } catch (err) {
      pushToast({
        tone: 'error',
        title: 'Couldn’t save changes',
        sub: err instanceof Error ? err.message : undefined,
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleMenuSelect = async (action: string) => {
    setMenuOpen(false);
    if (action === 'style') {
      router.push('/chat');
    } else if (action === 'edit') {
      setEditingField('name');
    } else if (action === 'category') {
      setCategoryPickerOpen(true);
    } else if (action === 'share') {
      const url = typeof window !== 'undefined' ? window.location.href : '';
      try {
        if (navigator.share) {
          await navigator.share({ title: form.name, url });
        } else {
          await navigator.clipboard.writeText(url);
          pushToast({ tone: 'success', title: 'Link copied' });
        }
      } catch {
        /* user dismissed the share sheet */
      }
    } else {
      // 'return' / 'delete' — no backend endpoints yet. Stay honest: never fake a
      // successful delete/return.
      pushToast({ tone: 'info', title: 'Not available yet', sub: 'This action isn’t wired up yet.' });
    }
  };

  const toggleFavorite = async () => {
    const next = !faved;
    setFaved(next); // optimistic
    try {
      await updateItem(id, { isFavorite: next, eventSource: 'closet_detail' });
    } catch {
      setFaved(!next); // revert on failure
    }
  };

  const displayRows = useMemo(() => {
    const rows: {
      key: string;
      label: string;
      value: string;
      editable: EditableField | 'category' | null;
      confKey: string;
    }[] = [
      { key: 'name', label: 'Name', value: form.name, editable: 'name', confKey: 'name' },
      { key: 'brand', label: 'Brand', value: form.brand || '—', editable: 'brand', confKey: 'brand' },
      { key: 'category', label: 'Category', value: CATEGORY_LABELS[category], editable: 'category', confKey: 'category' },
      { key: 'color', label: 'Color', value: form.color || '—', editable: 'color', confKey: 'color' },
      { key: 'size', label: 'Size', value: form.size || '—', editable: 'size', confKey: 'size' },
    ];
    if (quantity != null) {
      rows.push({ key: 'qty', label: 'Quantity', value: String(quantity), editable: null, confKey: 'quantity' });
    }
    rows.push({
      key: 'unitPrice',
      label: 'Unit price',
      value: form.unitPrice ? `${currencySymbol}${Number(form.unitPrice).toFixed(2)}` : '—',
      editable: 'unitPrice',
      confKey: 'unitPrice',
    });
    if (orderDate) {
      rows.push({
        key: 'ordered',
        label: 'Order date',
        value: new Date(orderDate).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }),
        editable: null,
        confKey: 'orderDate',
      });
    }
    return rows;
  }, [form, category, quantity, orderDate, currencySymbol]);

  // How many fields carry a real low-confidence score (drives the review banner).
  const lowFields = displayRows.filter((r) => (fieldConf[r.confKey] ?? 1) < 0.7).length;

  if (!isAuthed) {
    return null;
  }

  if (isItemLoading && !loadedOnce) {
    return (
      <AppShell>
        <div style={{ padding: '4px 20px' }}>
          <TopBar title="Item details" onBack={() => router.push('/closet')} />
          <div style={{ marginTop: 8 }} role="status" aria-label="Loading item">
            <SkDetail />
          </div>
        </div>
      </AppShell>
    );
  }

  if (!isItemLoading && error && !loadedOnce) {
    return (
      <AppShell scroll={false}>
        <div className="flex h-full flex-col items-center justify-center px-8 text-center">
          <h1 className="m-0 text-[20px] font-bold text-white">Couldn&rsquo;t load this item</h1>
          <p className="mb-6 mt-2 text-sm text-white/60">{error}</p>
          <Btn variant="primary" size="md" onClick={() => router.push('/closet')}>
            Back to closet
          </Btn>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      <div style={{ padding: `4px 20px ${NAV_CLEAR}px` }}>
        <TopBar
          title="Item details"
          onBack={() => router.push('/closet')}
          right={
            <div className="relative">
              <RoundBtn
                size={40}
                style={{ borderRadius: 14 }}
                aria-label="More actions"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                onClick={() => setMenuOpen((o) => !o)}
                icon={<MoreVertical size={18} />}
              />
              {menuOpen && (
                <>
                  <button
                    type="button"
                    aria-label="Close menu"
                    className="fixed inset-0 z-40 cursor-default border-none bg-transparent"
                    onClick={() => setMenuOpen(false)}
                  />
                  <div className="absolute right-0 z-50" style={{ top: 48 }}>
                    <ContextMenu
                      items={[
                        { id: 'style', label: 'Style this piece', sub: 'Build outfits around it', icon: <Spark size={16} /> },
                        { id: 'edit', label: 'Edit details', icon: <Pencil size={16} /> },
                        { id: 'category', label: 'Change category', icon: <Icon name="InterfaceSlider03" size={16} /> },
                        { id: 'share', label: 'Share', icon: <ExternalLink size={16} /> },
                        {
                          id: 'return',
                          label: 'Mark as returned',
                          sub: 'Coming soon',
                          icon: <Undo2 size={16} />,
                          disabled: true,
                          title: 'Coming soon',
                        },
                        { divider: true },
                        {
                          id: 'delete',
                          label: 'Delete from closet',
                          sub: 'Coming soon',
                          tone: 'danger',
                          icon: <Trash2 size={16} />,
                          disabled: true,
                          title: 'Coming soon',
                        },
                      ]}
                      onSelect={handleMenuSelect}
                    />
                  </div>
                </>
              )}
            </div>
          }
        />

        {/* Hero image — name + UPPERCASE brand overlaid, favourite disc, source chip. */}
        <div
          className="relative overflow-hidden"
          style={{
            borderRadius: 26,
            height: 300,
            marginTop: 4,
            border: '1px solid rgba(255,255,255,0.12)',
            boxShadow: '0 20px 44px -14px rgba(0,0,0,0.6)',
          }}
        >
          <ItemImage src={imageUrl} alt={form.name} fit="cover" emptyLabel="No image available" />
          <div
            className="pointer-events-none absolute inset-0"
            style={{ background: 'linear-gradient(to top, rgba(0,0,0,0.72), transparent 55%)' }}
            aria-hidden
          />
          <div className="absolute" style={{ left: 18, bottom: 15, right: 60 }}>
            <h1 className="m-0 truncate text-white" style={{ fontSize: 21, fontWeight: 700, letterSpacing: '-0.4px' }}>
              {form.name}
            </h1>
            {form.brand && (
              <div
                className="mt-1 truncate font-accent uppercase"
                style={{ color: M.soft, fontSize: 12, letterSpacing: '0.7px' }}
              >
                {form.brand}
              </div>
            )}
          </div>
          <div className="absolute" style={{ top: 13, right: 13 }}>
            <RoundBtn
              size={34}
              on={faved}
              aria-label={faved ? 'Remove from favorites' : 'Add to favorites'}
              onClick={toggleFavorite}
              icon={<Heart size={16} fill={faved ? 'currentColor' : 'none'} />}
            />
          </div>
          {fromGmail && (
            <span
              className="absolute inline-flex items-center"
              style={{
                left: 18,
                top: 14,
                gap: 6,
                padding: '5px 11px',
                borderRadius: 999,
                background: 'rgba(0,0,0,0.4)',
                backdropFilter: 'blur(10px)',
                WebkitBackdropFilter: 'blur(10px)',
                border: '1px solid rgba(255,255,255,0.16)',
                color: M.soft,
                fontSize: 11,
              }}
            >
              <Mail size={12} /> {merchant}
            </span>
          )}
        </div>

        {/* Low-confidence review banner — only when real field scores flag something. */}
        {lowFields > 0 && (
          <div
            className="flex items-center"
            style={{
              marginTop: 14,
              gap: 10,
              padding: '11px 14px',
              borderRadius: 15,
              background: 'rgba(240,162,59,0.12)',
              border: '1px solid rgba(240,162,59,0.32)',
              backdropFilter: 'blur(12px)',
              WebkitBackdropFilter: 'blur(12px)',
            }}
          >
            <span
              className="flex shrink-0 items-center justify-center font-bold"
              style={{
                width: 22,
                height: 22,
                borderRadius: '50%',
                background: 'rgba(240,162,59,0.18)',
                color: '#f0b566',
                fontSize: 14,
              }}
              aria-hidden
            >
              !
            </span>
            <span className="flex-1 text-white" style={{ fontSize: 12.8, lineHeight: 1.45 }}>
              {lowFields} field{lowFields === 1 ? ' was' : 's were'} read with low confidence — a 10-second check keeps
              outfits accurate.
            </span>
          </div>
        )}

        {/* Editable field rows — confidence dot · label · value/inline-edit · edit. */}
        <GlassCard tint="frost" padding={0} radius={24} style={{ marginTop: 14 }}>
          <div style={{ padding: '8px 18px' }}>
            {displayRows.map((row, i) => {
              const isEditingThis =
                row.editable !== null && row.editable !== 'category' && editingField === row.editable;
              const conf = fieldConf[row.confKey] ?? 1;
              const low = conf < 0.7;
              return (
                <div
                  key={row.key}
                  className="flex items-center"
                  style={{
                    gap: 11,
                    padding: '12.5px 2px',
                    borderBottom: i === displayRows.length - 1 ? 'none' : '1px solid rgba(255,255,255,0.07)',
                  }}
                >
                  <ConfidenceDot conf={conf} />
                  <span className="shrink-0" style={{ width: 86, color: M.faint, fontSize: 13 }}>
                    {row.label}
                  </span>
                  {isEditingThis ? (
                    <span
                      className="flex flex-1 items-center"
                      style={{
                        gap: 8,
                        padding: '7px 12px',
                        borderRadius: 11,
                        background: 'rgba(255,255,255,0.08)',
                        border: '1px solid rgba(75,226,214,0.5)',
                        boxShadow: '0 0 0 3px rgba(75,226,214,0.12)',
                      }}
                    >
                      <input
                        autoFocus
                        type={row.editable === 'unitPrice' ? 'number' : 'text'}
                        value={form[row.editable as EditableField]}
                        onChange={(e) => setForm((f) => ({ ...f, [row.editable as EditableField]: e.target.value }))}
                        onBlur={() => setEditingField(null)}
                        onKeyDown={(e) => e.key === 'Enter' && setEditingField(null)}
                        className="min-w-0 flex-1 border-none bg-transparent text-white outline-none"
                        style={{ fontSize: 14 }}
                        aria-label={row.label}
                      />
                    </span>
                  ) : (
                    <span className="flex-1 truncate text-white" style={{ fontSize: 14.5, fontWeight: 550 }}>
                      {row.value}
                    </span>
                  )}
                  {low && !isEditingThis && (
                    <span
                      className="inline-flex items-center"
                      style={{
                        height: 25,
                        padding: '0 10px',
                        borderRadius: 999,
                        fontSize: 11,
                        fontWeight: 600,
                        background: 'rgba(240,162,59,0.14)',
                        color: '#f0b566',
                        border: '1px solid rgba(240,162,59,0.4)',
                      }}
                    >
                      Confirm
                    </span>
                  )}
                  {row.editable !== null && !isEditingThis && (
                    <button
                      type="button"
                      aria-label={`Edit ${row.label.toLowerCase()}`}
                      onClick={() =>
                        row.editable === 'category'
                          ? setCategoryPickerOpen(true)
                          : setEditingField(row.editable as EditableField)
                      }
                      className="flex shrink-0 items-center"
                      style={{ color: M.ghost }}
                    >
                      <Pencil size={14} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </GlassCard>

        {/* Source line. */}
        <div
          className="flex items-center"
          style={{ ...M.glass(20), padding: '13px 16px', marginTop: 12, gap: 11 }}
        >
          <Link2 size={16} style={{ color: M.faint }} />
          <span className="flex-1" style={{ color: M.faint, fontSize: 12.5 }}>
            {merchant ? `From ${merchant}` : 'Added to your closet'}
          </span>
        </div>

        {/* Save. */}
        <div style={{ marginTop: 18 }}>
          <Btn
            variant="primary"
            size="md"
            fullWidth
            pending={isSaving}
            disabled={isSaving || !form.name.trim()}
            onClick={handleSave}
          >
            Save changes
          </Btn>
        </div>
      </div>

      {/* Category picker sheet (Change category — PATCHable, so fully real). */}
      <Sheet open={categoryPickerOpen} onClose={() => setCategoryPickerOpen(false)} title="Category">
        {CATEGORY_OPTIONS.map((c, i) => (
          <RadioRow
            key={c}
            first={i === 0}
            label={CATEGORY_LABELS[c]}
            on={category === c}
            onSelect={() => {
              setCategory(c);
              setCategoryPickerOpen(false);
            }}
          />
        ))}
      </Sheet>
    </AppShell>
  );
}
