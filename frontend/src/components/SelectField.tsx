import * as Select from "@radix-ui/react-select";
import { useState } from "react";
import styles from "./SelectField.module.css";

export type SelectOption = {
  value: string;
  label: string;
};

type SelectFieldProps = {
  id: string;
  name: string;
  value: string;
  options: readonly SelectOption[];
  onValueChange: (value: string) => void;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string | undefined;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
};

export function SelectField({
  id,
  name,
  value,
  options,
  onValueChange,
  disabled = false,
  invalid = false,
  describedBy,
  open: controlledOpen,
  onOpenChange,
}: SelectFieldProps) {
  const [localOpen, setLocalOpen] = useState(false);
  const open = controlledOpen ?? localOpen;
  function changeOpen(next: boolean) {
    setLocalOpen(next);
    onOpenChange?.(next);
  }
  return (
    <div className={styles.field}>
      <Select.Root
        open={open}
        onOpenChange={changeOpen}
        name={name}
        value={value}
        onValueChange={onValueChange}
        disabled={disabled}
        required
      >
        <Select.Trigger
          id={id}
          className={styles.trigger}
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
        >
          <Select.Value />
          <Select.Icon asChild>
            <svg className={styles.chevron} viewBox="0 0 16 16" aria-hidden="true">
              <path d="m4 6 4 4 4-4" />
            </svg>
          </Select.Icon>
        </Select.Trigger>
        <Select.Portal>
          <Select.Content
            className={styles.content}
            position="popper"
            align="start"
            sideOffset={6}
            collisionPadding={8}
          >
            <Select.ScrollUpButton className={styles.scrollButton}>
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path d="m4 10 4-4 4 4" />
              </svg>
            </Select.ScrollUpButton>
            <Select.Viewport className={styles.viewport}>
              {options.map((option) => (
                <Select.Item key={option.value} value={option.value} className={styles.item}>
                  <Select.ItemText>{option.label}</Select.ItemText>
                  <Select.ItemIndicator className={styles.indicator}>
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                      <path d="m3 8 3 3 7-7" />
                    </svg>
                  </Select.ItemIndicator>
                </Select.Item>
              ))}
            </Select.Viewport>
            <Select.ScrollDownButton className={styles.scrollButton}>
              <svg viewBox="0 0 16 16" aria-hidden="true">
                <path d="m4 6 4 4 4-4" />
              </svg>
            </Select.ScrollDownButton>
          </Select.Content>
        </Select.Portal>
      </Select.Root>
    </div>
  );
}
