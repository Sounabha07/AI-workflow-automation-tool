import { Switch } from "@/components/ui/switch";

export function BooleanField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3 text-[13px]">
      <span>{label}</span>
      <Switch checked={!!value} onCheckedChange={onChange} aria-label={label} />
    </div>
  );
}
