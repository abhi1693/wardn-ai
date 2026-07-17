import { FileUp } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { MCPRegistryServerResponse } from "@/lib/api/generated/model";

import {
  installValueFilename,
  installValueInputText,
  qualityScore,
  qualityScorePercent,
  qualityScoreTone,
  serverCategory,
  serverIconUrl,
  type InstallField,
  type InstallValue,
} from "./install-form-domain";

export function ServerPickerCard({
  entry,
  onSelect,
}: {
  entry: MCPRegistryServerResponse;
  onSelect: () => void;
}) {
  const score = qualityScore(entry);
  const iconUrl = serverIconUrl(entry);
  const description = entry.server.description?.trim();
  const category = serverCategory(entry);

  return (
    <button
      className="flex min-h-48 w-full flex-col rounded-md border bg-white p-4 text-left transition-colors hover:border-primary/50 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      onClick={onSelect}
      type="button"
    >
      <div className="flex items-start gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-md border bg-muted text-sm font-semibold text-muted-foreground">
          {iconUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              alt=""
              className="size-full object-cover"
              loading="lazy"
              referrerPolicy="no-referrer"
              src={iconUrl}
            />
          ) : (
            (entry.server.title || entry.server.name).slice(0, 1).toUpperCase()
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="break-words text-sm font-semibold leading-5 text-foreground">
            {entry.server.title || entry.server.name}
          </div>
          <div className="mt-0.5 break-words text-xs leading-4 text-muted-foreground">
            {category || entry.server.name}
          </div>
        </div>
      </div>

      {description ? (
        <p className="mt-4 line-clamp-4 text-sm leading-6 text-foreground">
          {description}
        </p>
      ) : (
        <div className="mt-4 text-sm leading-6 text-muted-foreground">
          No description provided.
        </div>
      )}

      <div className="mt-auto pt-4">
        <div className="flex items-center justify-between gap-3 text-xs">
          <span className="text-muted-foreground">Quality score</span>
          <span className="font-semibold text-foreground">
            {score === null ? "Pending" : `${score}/100`}
          </span>
        </div>
        <div className="mt-2 h-1 overflow-hidden rounded-full bg-muted">
          <div
            className={`h-full rounded-full ${qualityScoreTone(score)}`}
            style={{ width: `${qualityScorePercent(score)}%` }}
          />
        </div>
      </div>
    </button>
  );
}

export function InstallFieldControl({
  field,
  hasExistingValue = false,
  onChange,
  value,
}: {
  field: InstallField;
  hasExistingValue?: boolean;
  onChange: (value: InstallValue) => void;
  value: InstallValue;
}) {
  const inputId = `install-${field.name}`;

  if (field.format === "boolean") {
    return (
      <label className="flex items-start gap-3 rounded-md border p-3 text-sm">
        <input
          checked={installValueInputText(value) === "true"}
          className="mt-1"
          onChange={(event) => onChange(event.target.checked ? "true" : "false")}
          type="checkbox"
        />
        <span className="grid gap-1">
          <span className="font-medium">
            {field.name}
            {field.required ? <span className="text-red-600"> *</span> : null}
          </span>
          {field.description ? <span className="text-xs leading-5 text-muted-foreground">{field.description}</span> : null}
        </span>
      </label>
    );
  }

  if (field.format === "file") {
    const selectedFilename = installValueFilename(value);
    return (
      <div className="grid gap-2">
        <Label htmlFor={inputId}>
          {field.name}
          {field.required ? <span className="text-red-600"> *</span> : null}
        </Label>
        <div className="grid gap-2">
          <Input
            id={inputId}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) {
                onChange("");
                return;
              }
              void file.text().then((content) => {
                onChange({
                  type: "file",
                  filename: file.name,
                  content,
                });
              });
            }}
            type="file"
          />
          {selectedFilename ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <FileUp className="size-3.5" />
              {selectedFilename}
            </div>
          ) : hasExistingValue ? (
            <div className="text-xs text-muted-foreground">Configured file is saved.</div>
          ) : null}
        </div>
        {field.description ? <div className="text-xs leading-5 text-muted-foreground">{field.description}</div> : null}
      </div>
    );
  }

  return (
    <div className="grid gap-2">
      <Label htmlFor={inputId}>
        {field.name}
        {field.required ? <span className="text-red-600"> *</span> : null}
      </Label>
      {field.options.length > 0 || field.format === "select" ? (
        <Select onValueChange={onChange} value={installValueInputText(value)}>
          <SelectTrigger id={inputId}>
            <SelectValue placeholder="Default" />
          </SelectTrigger>
          <SelectContent>
            {field.options.map((option) => (
              <SelectItem key={option} value={option}>{option}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <Input
          autoComplete="off"
          id={inputId}
          onChange={(event) => onChange(event.target.value)}
          placeholder={field.secret && hasExistingValue ? "Configured value" : field.secret ? "Secret value" : "Value"}
          type={field.secret ? "password" : field.format === "integer" ? "number" : "text"}
          value={installValueInputText(value)}
        />
      )}
      {field.description ? <div className="text-xs leading-5 text-muted-foreground">{field.description}</div> : null}
    </div>
  );
}

