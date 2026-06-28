'use client';

// TODO: backend closet items have no per-field confidence; PATCH supports
// name/category/color/brand/size/unitPrice/currency/imageUrl only

import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { BookOpen, Heart, MoreVertical, Pencil } from 'lucide-react';

import type { ClosetItem, ClosetItemUpdate } from '@tailor/contracts';

import { useRequireAuth } from '@/lib/auth/useRequireAuth';
import { useClosetStore } from '@/stores/useClosetStore';
import { AppShell } from '@/components/layout/AppShell';
import { TopBar } from '@/components/ui/TopBar';
import { GlassCard } from '@/components/ui/GlassCard';
import { LightButton } from '@/components/ui/LightButton';

interface PageProps {
  params: { id: string };
}

const CATEGORIES = ['top', 'bottom', 'dress', 'outerwear', 'shoes', 'accessories', 'other'] as const;

const FALLBACK_IMG =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' width='430' height='430'><rect width='100%' height='100%' fill='%23333'/></svg>"
  );

// Editable form shape (strings for inputs).
type Editable = {
  name: string;
  brand: string;
  category: string;
  color: string;
  size: string;
  unitPrice: string;
  currency: string;
};

function fromItem(item: ClosetItem): Editable {
  return {
    name: item.name ?? '',
    brand: item.brand ?? '',
    category: item.category ?? '',
    color: item.color ?? '',
    size: item.size ?? '',
    unitPrice: item.unitPrice != null ? String(item.unitPrice) : '',
    currency: item.currency ?? '',
  };
}

/** One label/value row in the editable fields card. */
function DetailRow({
  label,
  field,
  type = 'text',
  form,
  editingField,
  setEditingField,
  onChange,
  display,
  readOnly,
  isLast,
}: {
  label: string;
  field?: keyof Editable;
  type?: string;
  form?: Editable;
  editingField?: keyof Editable | null;
  setEditingField?: (f: keyof Editable | null) => void;
  onChange?: (f: keyof Editable, v: string) => void;
  display: React.ReactNode;
  readOnly?: boolean;
  isLast?: boolean;
}) {
  const isEditing = !readOnly && field != null && editingField === field;

  return (
    <div
      className="flex items-center gap-2 px-2 py-3"
      style={{ borderBottom: isLast ? 'none' : '1px solid rgba(255,255,255,0.08)' }}
    >
      <span className="text-[13px]" style={{ width: 92, flexShrink: 0, color: 'rgba(255,255,255,0.6)' }}>
        {label}
      </span>

      <div className="min-w-0 flex-1">
        {isEditing && field && form && onChange ? (
          field === 'category' ? (
            <select
              autoFocus
              value={form.category}
              onChange={(e) => onChange('category', e.target.value)}
              onBlur={() => setEditingField?.(null)}
              className="w-full rounded-lg px-2 py-1.5 text-[15px] text-white outline-none"
              style={{ background: 'rgba(255,255,255,0.1)', border: '1px solid var(--tr-20)' }}
            >
              {CATEGORIES.map((c) => (
                <option key={c} value={c} style={{ color: '#000' }}>
                  {c.charAt(0).toUpperCase() + c.slice(1)}
                </option>
              ))}
            </select>
          ) : (
            <input
              autoFocus
              type={type}
              value={form[field]}
              onChange={(e) => onChange(field, e.target.value)}
              onBlur={() => setEditingField?.(null)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === 'Escape') setEditingField?.(null);
              }}
              className="w-full rounded-lg px-2 py-1.5 text-[15px] text-white outline-none"
              style={{ background: 'rgba(255,255,255,0.1)', border: '1px solid var(--tr-20)' }}
            />
          )
        ) : (
          <span className="text-[15px] text-white">{display}</span>
        )}
      </div>

      {!readOnly && field && setEditingField && (
        <button
          type="button"
          onClick={() => setEditingField(isEditing ? null : field)}
          aria-label={`Edit ${label}`}
          className="flex items-center justify-center text-white/60 transition-colors hover:text-white"
          style={{ width: 28, height: 28, flexShrink: 0 }}
        >
          <Pencil size={15} />
        </button>
      )}
    </div>
  );
}

export default function ItemDetailPage({ params }: PageProps) {
  const { id } = params;
  const router = useRouter();
  const { status } = useRequireAuth();
  const isAuth = status === 'authenticated';

  const fetchItem = useClosetStore((s) => s.fetchItem);
  const updateItem = useClosetStore((s) => s.updateItem);

  const [item, setItem] = useState<ClosetItem | null>(null);
  const [form, setForm] = useState<Editable | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [editingField, setEditingField] = useState<keyof Editable | null>(null);
  const [liked, setLiked] = useState(false);

  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  useEffect(() => {
    if (!isAuth) return;
    let active = true;
    setLoading(true);
    fetchItem(id)
      .then((it) => {
        if (!active) return;
        setItem(it);
        setForm(fromItem(it));
        setNotFound(false);
      })
      .catch(() => {
        if (active) setNotFound(true);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [id, fetchItem, isAuth]);

  function setField(f: keyof Editable, v: string) {
    setForm((prev) => (prev ? { ...prev, [f]: v } : prev));
  }

  // Build the changed-fields diff for PATCH.
  function buildUpdates(): ClosetItemUpdate {
    if (!item || !form) return {};
    const updates: ClosetItemUpdate = {};
    if (form.name.trim() && form.name.trim() !== item.name) updates.name = form.name.trim();
    if (form.brand.trim() !== (item.brand ?? '')) updates.brand = form.brand.trim();
    if (form.category && form.category !== item.category) {
      updates.category = form.category as ClosetItem['category'];
    }
    if (form.color.trim() !== (item.color ?? '')) updates.color = form.color.trim();
    if (form.size.trim() !== (item.size ?? '')) updates.size = form.size.trim();
    if (form.currency.trim() !== (item.currency ?? '')) updates.currency = form.currency.trim().toUpperCase();
    const parsedPrice = form.unitPrice.trim() === '' ? undefined : parseFloat(form.unitPrice);
    if (
      parsedPrice != null &&
      !Number.isNaN(parsedPrice) &&
      parsedPrice !== (item.unitPrice ?? undefined)
    ) {
      updates.unitPrice = parsedPrice;
    }
    return updates;
  }

  const hasChanges = Object.keys(buildUpdates()).length > 0;

  async function handleSave() {
    const updates = buildUpdates();
    if (Object.keys(updates).length === 0) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      const updated = await updateItem(id, updates);
      setItem(updated);
      setForm(fromItem(updated));
      setEditingField(null);
      setSaveMsg({ type: 'success', text: 'Changes saved' });
      setTimeout(() => setSaveMsg(null), 2500);
    } catch (err) {
      setSaveMsg({ type: 'error', text: err instanceof Error ? err.message : 'Failed to save' });
    } finally {
      setSaving(false);
    }
  }

  if (status === 'loading' || !isAuth) {
    return (
      <AppShell contentClassName="pt-16">
        <div />
      </AppShell>
    );
  }

  if (loading) {
    return (
      <AppShell>
        <div className="h-[360px] w-full bg-white/5 animate-pulse" />
        <div className="px-6 pt-6">
          <div className="h-7 w-44 rounded bg-white/5 animate-pulse" />
        </div>
      </AppShell>
    );
  }

  if (notFound || !item || !form) {
    return (
      <AppShell scroll={false}>
        <div className="flex h-full flex-col items-center justify-center px-8 text-center">
          <h1 className="m-0 text-[22px] font-bold text-white">Item not found</h1>
          <p className="mt-2 mb-6 text-[14.5px]" style={{ color: 'rgba(255,255,255,0.65)' }}>
            This item may have been removed.
          </p>
          <LightButton onClick={() => router.push('/closet')} style={{ height: 48, padding: '0 26px' }}>
            Back to closet
          </LightButton>
        </div>
      </AppShell>
    );
  }

  const priceDisplay =
    form.unitPrice.trim() && !Number.isNaN(parseFloat(form.unitPrice))
      ? `${parseFloat(form.unitPrice).toFixed(2)}${form.currency ? ` ${form.currency.toUpperCase()}` : ''}`
      : '—';

  return (
    <AppShell>
      {/* Hero image */}
      <div className="relative" style={{ height: 360 }}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={item.imageUrl || FALLBACK_IMG}
          alt={item.name}
          className="absolute inset-0 h-full w-full object-cover"
        />
        <div
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(180deg, rgba(0,0,0,0.5) 0%, transparent 30%, rgba(30,30,30,0.95) 100%)',
          }}
        />
        <div className="absolute left-0 right-0" style={{ top: 48 }}>
          <div className="px-4">
            <TopBar right={<MoreVertical size={20} />} />
          </div>
        </div>
      </div>

      {/* Body */}
      <div style={{ marginTop: -40, padding: '0 24px 120px' }}>
        {/* Title row */}
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="m-0 text-[27px] font-bold leading-tight text-white" style={{ letterSpacing: '-0.4px' }}>
                {form.name || 'Untitled'}
              </h1>
              <button
                type="button"
                onClick={() => setEditingField('name')}
                aria-label="Edit name"
                className="text-white/55 transition-colors hover:text-white"
              >
                <Pencil size={16} />
              </button>
            </div>
            {form.brand && (
              <p
                className="m-0 mt-1 font-accent uppercase"
                style={{ color: 'rgba(255,255,255,0.6)', fontSize: 12, letterSpacing: '0.5px' }}
              >
                {form.brand}
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => setLiked((v) => !v)}
            aria-label={liked ? 'Unfavourite' : 'Favourite'}
            className="flex items-center justify-center transition-transform active:scale-90"
            style={{
              width: 40,
              height: 40,
              borderRadius: '50%',
              flexShrink: 0,
              background: 'rgba(0,0,0,0.28)',
              border: '1px solid var(--tr-20)',
              color: liked ? 'var(--mint)' : 'rgba(255,255,255,0.85)',
            }}
          >
            <Heart size={18} fill={liked ? 'currentColor' : 'none'} />
          </button>
        </div>

        {/* Editable fields card */}
        <div className="mt-5">
          <GlassCard tint="frost" padding={4}>
            <DetailRow
              label="Name"
              field="name"
              form={form}
              editingField={editingField}
              setEditingField={setEditingField}
              onChange={setField}
              display={form.name || '—'}
            />
            <DetailRow
              label="Brand"
              field="brand"
              form={form}
              editingField={editingField}
              setEditingField={setEditingField}
              onChange={setField}
              display={form.brand || '—'}
            />
            <DetailRow
              label="Category"
              field="category"
              form={form}
              editingField={editingField}
              setEditingField={setEditingField}
              onChange={setField}
              display={
                form.category ? form.category.charAt(0).toUpperCase() + form.category.slice(1) : '—'
              }
            />
            <DetailRow
              label="Color"
              field="color"
              form={form}
              editingField={editingField}
              setEditingField={setEditingField}
              onChange={setField}
              display={form.color || '—'}
            />
            <DetailRow
              label="Size"
              field="size"
              form={form}
              editingField={editingField}
              setEditingField={setEditingField}
              onChange={setField}
              display={form.size || '—'}
            />
            {/* Read-only: quantity is not patchable */}
            <DetailRow
              label="Quantity"
              readOnly
              display={item.quantity != null ? String(item.quantity) : '—'}
            />
            <DetailRow
              label="Unit price"
              field="unitPrice"
              type="number"
              form={form}
              editingField={editingField}
              setEditingField={setEditingField}
              onChange={setField}
              display={priceDisplay}
            />
            {/* Read-only: orderDate is not patchable */}
            <DetailRow label="Order date" readOnly display={item.orderDate || '—'} />
            {/* Read-only: merchant is not patchable */}
            <DetailRow
              label="Source"
              readOnly
              isLast
              display={item.merchant ? `From ${item.merchant}` : '—'}
            />
          </GlassCard>
        </div>

        {/* Provenance line */}
        {item.merchant && (
          <div className="mt-5 flex items-center gap-2" style={{ color: 'rgba(255,255,255,0.55)' }}>
            <BookOpen size={15} />
            <span className="text-[13px]">From {item.merchant}</span>
          </div>
        )}

        {/* Save */}
        <div className="mt-4">
          {saveMsg && (
            <p
              className="mb-2 text-[13px] font-medium"
              style={{ color: saveMsg.type === 'success' ? 'var(--success)' : 'var(--danger)' }}
            >
              {saveMsg.text}
            </p>
          )}
          <LightButton fullWidth onClick={handleSave} disabled={saving || !hasChanges}>
            {saving ? 'Saving…' : 'Save changes'}
          </LightButton>
        </div>
      </div>
    </AppShell>
  );
}
