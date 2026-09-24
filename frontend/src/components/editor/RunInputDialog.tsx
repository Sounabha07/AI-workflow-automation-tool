import { useEffect, useState } from "react";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";

export interface InputFieldDef {
  name: string;
  label?: string;
  type?: "text" | "json";
  required?: boolean;
  description?: string;
}

export function RunInputDialog({
  open,
  onOpenChange,
  fields,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  fields: InputFieldDef[];
  onSubmit: (values: Record<string, unknown>) => void;
}) {
  const [raw, setRaw] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (open) {
      setRaw({});
      setErrors({});
    }
  }, [open]);

  const submit = () => {
    const values: Record<string, unknown> = {};
    const nextErrors: Record<string, string> = {};

    for (const f of fields) {
      const text = raw[f.name] ?? "";
      if (f.required && !text.trim()) {
        nextErrors[f.name] = "This field is required.";
        continue;
      }
      if (!text.trim()) continue;
      if (f.type === "json") {
        try {
          values[f.name] = JSON.parse(text);
        } catch {
          nextErrors[f.name] = "Enter valid JSON.";
        }
      } else {
        values[f.name] = text;
      }
    }

    if (Object.keys(nextErrors).length) {
      setErrors(nextErrors);
      return;
    }
    onSubmit(values);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogTitle>Run workflow</DialogTitle>
        <DialogDescription>Fill in the fields this workflow's input block asks for.</DialogDescription>

        <div className="space-y-4">
          {fields.map((f) => (
            <div key={f.name}>
              <Label htmlFor={`ri-${f.name}`}>
                {f.label || f.name}
                {f.required && <span className="text-err"> *</span>}
              </Label>
              {f.type === "json" ? (
                <Textarea
                  id={`ri-${f.name}`}
                  className="mt-1.5"
                  value={raw[f.name] ?? ""}
                  onChange={(e) => setRaw((r) => ({ ...r, [f.name]: e.target.value }))}
                  placeholder="{}"
                />
              ) : (
                <Input
                  id={`ri-${f.name}`}
                  className="mt-1.5"
                  value={raw[f.name] ?? ""}
                  onChange={(e) => setRaw((r) => ({ ...r, [f.name]: e.target.value }))}
                />
              )}
              {f.description && <p className="mt-1 text-xs text-ink-3">{f.description}</p>}
              {errors[f.name] && <p className="mt-1 text-xs text-err">{errors[f.name]}</p>}
            </div>
          ))}
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" onClick={submit}>
            Run
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
