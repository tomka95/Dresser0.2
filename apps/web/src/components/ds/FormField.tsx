'use client';

import React from 'react';

import { Field } from './Field';

interface FormFieldProps {
  label: string;
  value: string;
  onChange?: (value: string) => void;
  placeholder?: string;
  multiline?: boolean;
  type?: string;
  disabled?: boolean;
  className?: string;
}

/**
 * Labeled dark form field — legacy API kept intact; renders via the §0 Field
 * (glass box, mint focus ring).
 */
export function FormField({
  label,
  value,
  onChange,
  placeholder,
  multiline = false,
  type = 'text',
  disabled = false,
  className,
}: FormFieldProps) {
  return (
    <Field
      label={label}
      value={value}
      onChange={onChange}
      placeholder={placeholder}
      multiline={multiline}
      type={type}
      disabled={disabled}
      className={className}
    />
  );
}
