// Select, dropdown menu and slide-over sheet built on Radix primitives so keyboard
// navigation, focus trapping and ARIA wiring come from the library rather than by hand.
import * as SelectPrimitive from '@radix-ui/react-select';
import * as DropdownMenuPrimitive from '@radix-ui/react-dropdown-menu';
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { Check, ChevronDown, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { inputClass } from './ui.jsx';

export const Select = SelectPrimitive.Root;
export const SelectValue = SelectPrimitive.Value;
export const SelectGroup = SelectPrimitive.Group;
export const SelectSeparator = SelectPrimitive.Separator;

export function SelectTrigger({ className, children, ...props }) {
  return (
    <SelectPrimitive.Trigger
      className={cn(inputClass, 'flex items-center justify-between gap-2 text-left', className)}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild><ChevronDown className="size-3.5 text-fg-subtle" /></SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

export function SelectContent({ className, children, ...props }) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        position="popper"
        sideOffset={4}
        className={cn(
          'z-50 max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-[8px] border border-border bg-surface p-1 shadow-[0_8px_24px_rgb(0_0_0/0.12)]',
          className
        )}
        {...props}
      >
        <SelectPrimitive.Viewport>{children}</SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

export function SelectItem({ className, children, ...props }) {
  return (
    <SelectPrimitive.Item
      className={cn(
        'relative flex cursor-pointer select-none items-center gap-2 rounded-[5px] py-1.5 pl-2 pr-7 text-[13px] text-fg outline-none data-[highlighted]:bg-surface-2 data-[state=checked]:font-medium',
        className
      )}
      {...props}
    >
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
      <SelectPrimitive.ItemIndicator className="absolute right-2"><Check className="size-3.5 text-accent" /></SelectPrimitive.ItemIndicator>
    </SelectPrimitive.Item>
  );
}

export function SelectLabel({ className, ...props }) {
  return <SelectPrimitive.Label className={cn('px-2 py-1.5 text-[12px] text-fg-subtle', className)} {...props} />;
}

export const DropdownMenu = DropdownMenuPrimitive.Root;
export const DropdownMenuTrigger = DropdownMenuPrimitive.Trigger;

export function DropdownMenuContent({ className, align = 'end', sideOffset = 4, ...props }) {
  return (
    <DropdownMenuPrimitive.Portal>
      <DropdownMenuPrimitive.Content
        align={align}
        sideOffset={sideOffset}
        className={cn(
          'z-50 min-w-[180px] overflow-hidden rounded-[8px] border border-border bg-surface p-1 shadow-[0_8px_24px_rgb(0_0_0/0.12)]',
          className
        )}
        {...props}
      />
    </DropdownMenuPrimitive.Portal>
  );
}

export function DropdownMenuItem({ className, ...props }) {
  return (
    <DropdownMenuPrimitive.Item
      className={cn(
        'flex cursor-pointer select-none items-center gap-2 rounded-[5px] px-2 py-1.5 text-[13px] text-fg outline-none data-[highlighted]:bg-surface-2 [&_svg]:size-3.5',
        className
      )}
      {...props}
    />
  );
}

export function DropdownMenuSeparator({ className, ...props }) {
  return <DropdownMenuPrimitive.Separator className={cn('my-1 h-px bg-border', className)} {...props} />;
}

export const Sheet = DialogPrimitive.Root;
export const SheetTrigger = DialogPrimitive.Trigger;
export const SheetClose = DialogPrimitive.Close;

export function SheetContent({ className, children, ...props }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40 data-[state=open]:animate-in" />
      <DialogPrimitive.Content
        className={cn(
          'fixed inset-y-0 right-0 z-50 flex w-full max-w-[420px] flex-col border-l border-border bg-surface shadow-[-16px_0_40px_rgb(0_0_0/0.10)] focus:outline-none',
          className
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close className="absolute right-4 top-4 rounded-[6px] p-1 text-fg-subtle hover:bg-surface-2 hover:text-fg" aria-label="Close">
          <X className="size-4" />
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function SheetHeader({ className, ...props }) {
  return <div className={cn('border-b border-border px-5 py-4', className)} {...props} />;
}

export function SheetBody({ className, ...props }) {
  return <div className={cn('flex-1 overflow-y-auto px-5 py-4', className)} {...props} />;
}

export function SheetTitle({ className, ...props }) {
  return <DialogPrimitive.Title className={cn('text-[15px] font-semibold text-fg', className)} {...props} />;
}

export function SheetDescription({ className, ...props }) {
  return <DialogPrimitive.Description className={cn('mt-1 text-[12.5px] text-fg-muted', className)} {...props} />;
}

export function SheetFooter({ className, ...props }) {
  return <div className={cn('flex items-center gap-2 border-t border-border px-5 py-3', className)} {...props} />;
}

// Label on the left, value on the right. Used instead of pills for plain values.
export function KeyValue({ label, children, className, mono = false }) {
  return (
    <div className={cn('flex items-start justify-between gap-6 border-b border-border py-2 last:border-0', className)}>
      <dt className="shrink-0 text-[12.5px] text-fg-subtle">{label}</dt>
      <dd className={cn('text-right text-[13px] text-fg', mono && 'font-mono text-[12px]')}>{children}</dd>
    </div>
  );
}

export function FieldGroup({ label, children }) {
  return (
    <div>
      <div className="mb-1.5 text-[12.5px] font-medium text-fg-muted">{label}</div>
      {children}
    </div>
  );
}