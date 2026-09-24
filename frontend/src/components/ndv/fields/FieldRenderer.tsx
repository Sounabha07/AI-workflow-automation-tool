import type { FieldSchema } from "@/api/types";
import { isFieldVisible } from "@/lib/showWhen";
import { ScalarField } from "./ScalarField";
import { BooleanField } from "./BooleanField";
import { OptionsField } from "./OptionsField";
import { KeyValueListField } from "./KeyValueListField";
import { FieldDefinitionsField } from "./FieldDefinitionsField";
import { SwitchRulesField } from "./SwitchRulesField";

export function FieldRenderer({
  field,
  config,
  outputs,
  onChange,
}: {
  field: FieldSchema;
  config: Record<string, unknown>;
  outputs: Record<string, unknown>;
  onChange: (name: string, value: unknown) => void;
}) {
  if (!isFieldVisible(field.show_when, config)) return null;

  const value = config[field.name] ?? field.default;
  const set = (v: unknown) => onChange(field.name, v);

  switch (field.type) {
    case "boolean":
      return <BooleanField label={field.label} value={!!value} onChange={set} />;
    case "options":
      return (
        <OptionsField
          label={field.label}
          value={String(value ?? "")}
          options={field.options ?? []}
          onChange={set}
        />
      );
    case "key_value_list":
      return <KeyValueListField label={field.label} value={(value as any) ?? []} outputs={outputs} onChange={set} />;
    case "field_definitions":
      return <FieldDefinitionsField value={(value as any) ?? []} onChange={set} />;
    case "switch_rules":
      return <SwitchRulesField value={(value as any) ?? []} onChange={set} />;
    case "number":
      return (
        <ScalarField
          label={field.label}
          value={value}
          fieldType="number"
          outputs={outputs}
          required={field.required}
          placeholder={field.placeholder}
          onChange={set}
        />
      );
    case "json":
      return (
        <ScalarField
          label={field.label}
          value={value}
          fieldType="json"
          outputs={outputs}
          required={field.required}
          placeholder={field.placeholder}
          onChange={set}
        />
      );
    case "string":
    default:
      return (
        <ScalarField
          label={field.label}
          value={value}
          fieldType="string"
          outputs={outputs}
          required={field.required}
          placeholder={field.placeholder}
          sensitive={field.sensitive}
          onChange={set}
        />
      );
  }
}
