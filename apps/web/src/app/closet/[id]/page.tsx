'use client';

/**
 * /closet/[id] — full item detail (design: hero image, editable field rows with
 * per-field confidence cues, source line, save).
 *
 * REAL: GET /closet/{id} + PATCH /closet/{id} (name/brand/category/color/size/
 * unitPrice). NOT yet backend-backed: per-field confidence (no field-level scores
 * on closet items — dots read "confirmed"), favorite heart (local), quantity &
 * order date (render read-only; PATCH doesn't accept them), delete / mark-returned
 * (no endpoints).
 */

import React, { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Heart, MoreVertical, Pencil, BookOpen } from 'lucide-react';
import { useClosetStore } from '@/stores/useClosetStore';
import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { ItemImage } from '@/components/ui/ItemImage';
import { ConfidenceDot } from '@/components/ui/ConfidenceDot';
import { ContextMenu, DSButton, GlassCard, RadioRow, Sheet, TopBar } from '@/components/ds';
import type { ClosetItemUpdate } from '@tailor/contracts';

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

const FIELD_LABELS: Record<EditableField, string> = {
  name: 'Name',
  brand: 'Brand',
  color: 'Color',
  size: 'Size',
  unitPrice: 'Unit price',
};

export default function ItemDetailsPage({ params }: ItemDetailsPageProps) {
  const router = useRouter();
  const { id } = params;

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
  const [loadedOnce, setLoadedOnce] = useState(false);

  const [editingField, setEditingField] = useState<EditableField | null>(null);
  const [categoryPickerOpen, setCategoryPickerOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [menuNote, setMenuNote] = useState<string | null>(null);
  const [faved, setFaved] = useState(false); // local-only affordance

  const [isSaving, setIsSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

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
        setLoadedOnce(true);
      })
      .catch(() => {
        // Error handled by store, component shows error view
      });
  }, [id, fetchItem, isAuthed]);

  const currencySymbol = currency === 'GBP' ? '£' : currency === 'EUR' ? '€' : '$';

  // Per-field confidence — no backend scores on closet items, so every field
  // reads "confirmed" (mint). The low-confidence banner appears only if a field
  // ever carries a low score.
  const fieldConf: number = 1;
  const lowFields: number = 0;

  const handleSave = async () => {
    setIsSaving(true);
    setSaveMessage(null);
    try {
      const updates: ClosetItemUpdate = {
        name: form.name.trim(),
        category,
      };
      if (form.brand.trim()) updates.brand = form.brand.trim();
      if (form.color.trim()) updates.color = form.color.trim();
      if (form.size.trim()) updates.size = form.size.trim();
      const price = Number(form.unitPrice);
      if (form.unitPrice.trim() && Number.isFinite(price)) updates.unitPrice = price;

      await updateItem(id, updates);
      setEditingField(null);
      setSaveMessage({ type: 'success', text: 'Changes saved' });
      setTimeout(() => setSaveMessage(null), 3000);
    } catch (err) {
      setSaveMessage({
        type: 'error',
        text: err instanceof Error ? err.message : 'Failed to save changes',
      });
    } finally {
      setIsSaving(false);
    }
  };

  const handleMenuSelect = async (action: string) => {
    setMenuOpen(false);
    if (action === 'category') {
      setCategoryPickerOpen(true);
    } else if (action === 'share') {
      const url = typeof window !== 'undefined' ? window.location.href : '';
      try {
        if (navigator.share) {
          await navigator.share({ title: form.name, url });
        } else {
          await navigator.clipboard.writeText(url);
          setMenuNote('Link copied');
          setTimeout(() => setMenuNote(null), 2500);
        }
      } catch {
        /* user dismissed the share sheet */
      }
    } else {
      // 'return' / 'delete' — no backend endpoints yet.
      setMenuNote('Coming soon — this action isn’t wired up yet.');
      setTimeout(() => setMenuNote(null), 3000);
    }
  };

  const displayRows = useMemo(() => {
    const rows: { key: string; label: string; value: string; editable: EditableField | 'category' | null }[] = [
      { key: 'name', label: 'Name', value: form.name, editable: 'name' },
      { key: 'brand', label: 'Brand', value: form.brand || '—', editable: 'brand' },
      { key: 'category', label: 'Category', value: CATEGORY_LABELS[category], editable: 'category' },
      { key: 'color', label: 'Color', value: form.color || '—', editable: 'color' },
      { key: 'size', label: 'Size', value: form.size || '—', editable: 'size' },
    ];
    if (quantity != null) rows.push({ key: 'qty', label: 'Quantity', value: String(quantity), editable: null });
    rows.push({
      key: 'unitPrice',
      label: 'Unit price',
      value: form.unitPrice ? `${currencySymbol}${Number(form.unitPrice).toFixed(2)}` : '—',
      editable: 'unitPrice',
    });
    if (orderDate) {
      rows.push({
        key: 'ordered',
        label: 'Order date',
        value: new Date(orderDate).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }),
        editable: null,
      });
    }
    return rows;
  }, [form, category, quantity, orderDate, currencySymbol]);

  if (!isAuthed) {
    return null;
  }

  if (isItemLoading && !loadedOnce) {
    return (
      <AppShell scroll={false}>
        <div className="flex h-full items-center justify-center">
          <div
            role="status"
            aria-label="Loading item"
            className="h-8 w-8 rounded-full"
            style={{ border: '3px solid var(--tr-20)', borderTopColor: 'var(--mint)', animation: 'tailor-spin 0.8s linear infinite' }}
          />
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
          <DSButton variant="light" pill onClick={() => router.push('/closet')} style={{ height: 48, padding: '0 26px' }}>
            Back to closet
          </DSButton>
        </div>
      </AppShell>
    );
  }

  return (
    <AppShell>
      {/* Hero image */}
      <div className="relative" style={{ height: 360 }}>
        <ItemImage src={imageUrl} alt={form.name} fit="cover" emptyLabel="No image available" />
        <div
          className="pointer-events-none absolute inset-0"
          style={{ background: 'linear-gradient(180deg, rgba(0,0,0,0.5) 0%, transparent 30%, rgba(30,30,30,0.95) 100%)' }}
          aria-hidden
        />
        <div className="absolute left-4 right-4" style={{ top: 48 }}>
          <TopBar
            onBack={() => router.push('/closet')}
            right={
              <button
                type="button"
                aria-label="More"
                onClick={() => setMenuOpen((o) => !o)}
                className="flex h-10 w-10 items-center justify-center text-white"
              >
                <MoreVertical size={20} />
              </button>
            }
          />
        </div>

        {/* ⋮ contextual menu */}
        {menuOpen && (
          <>
            <button
              type="button"
              aria-label="Close menu"
              className="fixed inset-0 z-40 cursor-default border-none bg-transparent"
              onClick={() => setMenuOpen(false)}
            />
            <div className="absolute right-5 z-50" style={{ top: 96, width: 230 }}>
              <ContextMenu
                items={[
                  { id: 'category', label: 'Change category', icon: <Pencil size={17} /> },
                  { id: 'share', label: 'Share', icon: <BookOpen size={17} /> },
                  { id: 'return', label: 'Mark as returned', icon: <MoreVertical size={17} /> },
                  { divider: true },
                  { id: 'delete', label: 'Delete item', tone: 'danger', icon: <MoreVertical size={17} /> },
                ]}
                onSelect={handleMenuSelect}
              />
            </div>
          </>
        )}
      </div>

      <div className="relative" style={{ padding: '0 24px 120px', marginTop: -40 }}>
        {/* Title row */}
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="m-0 text-[27px] font-bold tracking-[-0.4px] text-white">{form.name}</h1>
              <button
                type="button"
                aria-label="Rename item"
                onClick={() => setEditingField('name')}
                className="text-white/70 hover:text-white"
              >
                <Pencil size={17} />
              </button>
            </div>
            {form.brand && (
              <div
                className="mt-1 font-accent uppercase"
                style={{ color: 'rgba(255,255,255,0.6)', fontSize: 13, letterSpacing: '0.5px' }}
              >
                {form.brand}
              </div>
            )}
          </div>
          <button
            type="button"
            aria-label={faved ? 'Unfavorite' : 'Favorite'}
            onClick={() => setFaved((f) => !f)}
            className="flex shrink-0 items-center justify-center rounded-full transition-transform active:scale-90"
            style={{
              width: 44,
              height: 44,
              border: '1px solid var(--tr-20)',
              background: 'rgba(0,0,0,0.3)',
              color: faved ? 'var(--mint)' : 'rgba(255,255,255,0.85)',
            }}
          >
            <Heart size={20} fill={faved ? 'currentColor' : 'none'} />
          </button>
        </div>

        {menuNote && (
          <p className="mt-3 rounded-xl px-3 py-2 text-center text-[12.5px]" style={{ background: 'var(--tr-10)', color: 'rgba(255,255,255,0.75)' }}>
            {menuNote}
          </p>
        )}

        {/* Low-confidence banner — only when field-level scores flag something. */}
        {lowFields > 0 && (
          <GlassCard tint="scrim" padding={14} className="my-[18px] flex items-center gap-3">
            <span
              className="flex shrink-0 items-center justify-center rounded-full text-[17px] font-extrabold"
              style={{ width: 32, height: 32, background: 'rgba(240,162,59,0.18)', color: 'var(--amber)' }}
            >
              !
            </span>
            <div className="flex-1 text-[13.5px] leading-snug text-white/85">
              {lowFields} field{lowFields === 1 ? '' : 's'} need a quick check — we weren&rsquo;t fully sure.
            </div>
          </GlassCard>
        )}

        {/* Editable fields */}
        <GlassCard tint="frost" padding={4} className={lowFields > 0 ? '' : 'mt-[18px]'}>
          <div style={{ padding: '4px 16px' }}>
            {displayRows.map((row, i) => {
              const isEditingThis = row.editable !== null && row.editable !== 'category' && editingField === row.editable;
              return (
                <div
                  key={row.key}
                  className="flex items-center gap-3"
                  style={{ padding: '13px 0', borderTop: i === 0 ? 'none' : '1px solid var(--tr-10)' }}
                >
                  <div className="w-[92px] shrink-0 text-[13px] text-white/60">{row.label}</div>
                  <div className="flex min-w-0 flex-1 items-center gap-2">
                    <ConfidenceDot conf={fieldConf} />
                    {isEditingThis ? (
                      <input
                        autoFocus
                        type={row.editable === 'unitPrice' ? 'number' : 'text'}
                        value={form[row.editable as EditableField]}
                        onChange={(e) =>
                          setForm((f) => ({ ...f, [row.editable as EditableField]: e.target.value }))
                        }
                        onBlur={() => setEditingField(null)}
                        onKeyDown={(e) => e.key === 'Enter' && setEditingField(null)}
                        className="min-w-0 flex-1 rounded-lg px-2 py-1 text-[15px] text-white outline-none"
                        style={{ background: 'rgba(255,255,255,0.1)', border: '1px solid var(--tr-20)' }}
                        aria-label={row.label}
                      />
                    ) : (
                      <span className="truncate text-[15px] font-medium text-white">{row.value}</span>
                    )}
                  </div>
                  {row.editable !== null && !isEditingThis && (
                    <button
                      type="button"
                      aria-label={`Edit ${row.label.toLowerCase()}`}
                      onClick={() =>
                        row.editable === 'category'
                          ? setCategoryPickerOpen(true)
                          : setEditingField(row.editable as EditableField)
                      }
                      className="shrink-0 text-white/60 hover:text-white"
                    >
                      <Pencil size={15} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </GlassCard>

        {/* Source line */}
        <div className="mx-0.5 my-4 flex items-center gap-2 text-[13px] text-white/60">
          <BookOpen size={15} />
          <span>{merchant ? `From ${merchant}` : 'Added to your closet'}</span>
        </div>

        {saveMessage && (
          <p
            className="mb-3 text-center text-[13px] font-medium"
            style={{ color: saveMessage.type === 'success' ? 'var(--success)' : 'var(--danger)' }}
          >
            {saveMessage.text}
          </p>
        )}

        <DSButton
          variant="light"
          fullWidth
          pill
          loading={isSaving}
          disabled={isSaving || !form.name.trim()}
          onClick={handleSave}
        >
          {isSaving ? 'Saving…' : 'Save changes'}
        </DSButton>
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
