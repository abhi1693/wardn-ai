import { Plus, Trash2 } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

import {
  emptyEnvironment,
  emptyHeader,
  emptyPackage,
  emptyPackageArgument,
  emptyRemote,
  PACKAGE_ARGUMENT_FORMAT_OPTIONS,
  PACKAGE_RUNTIME_OPTIONS,
  type EnvironmentField,
  type HeaderField,
  type PackageArgumentField,
  type PackageTarget,
  type RemoteTarget,
} from "./server-form-domain";

type RemoteEndpointsSectionProps = {
  remotes: RemoteTarget[];
  setRemotes: Dispatch<SetStateAction<RemoteTarget[]>>;
  updateRemote: (id: string, patch: Partial<RemoteTarget>) => void;
  updateRemoteHeader: (remoteId: string, headerId: string, patch: Partial<HeaderField>) => void;
};

export function RemoteEndpointsSection({
  remotes,
  setRemotes,
  updateRemote,
  updateRemoteHeader,
}: RemoteEndpointsSectionProps) {
  return (
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Remote Endpoints</CardTitle>
          <Button onClick={() => setRemotes((current) => [...current, emptyRemote()])} type="button" variant="outline">
            <Plus className="size-4" />
            Add remote
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {remotes.map((remote, index) => (
            <div className="space-y-4 rounded-md border p-4" key={remote.id}>
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">Remote {index + 1}</div>
                <Button
                  aria-label={`Remove remote ${index + 1}`}
                  onClick={() => setRemotes((current) => current.filter((item) => item.id !== remote.id))}
                  size="icon"
                  type="button"
                  variant="outline"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
              <div className="grid gap-4">
                <div className="grid gap-2">
                  <Label htmlFor={`${remote.id}-url`}>URL</Label>
                  <Input
                    id={`${remote.id}-url`}
                    onChange={(event) => updateRemote(remote.id, { url: event.target.value })}
                    placeholder="https://example.com/mcp"
                    value={remote.url}
                  />
                </div>
              </div>
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium">Headers</div>
                  <Button
                    onClick={() =>
                      updateRemote(remote.id, { headers: [...remote.headers, emptyHeader()] })
                    }
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    <Plus className="size-4" />
                    Add header
                  </Button>
                </div>
                {remote.headers.map((header) => (
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_auto_auto_auto]" key={header.id}>
                    <Input
                      onChange={(event) =>
                        updateRemoteHeader(remote.id, header.id, { name: event.target.value })
                      }
                      placeholder="Header name"
                      value={header.name}
                    />
                    <Input
                      onChange={(event) =>
                        updateRemoteHeader(remote.id, header.id, { description: event.target.value })
                      }
                      placeholder="Description"
                      value={header.description}
                    />
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        checked={header.required}
                        onChange={(event) =>
                          updateRemoteHeader(remote.id, header.id, { required: event.target.checked })
                        }
                        type="checkbox"
                      />
                      Required
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        checked={header.secret}
                        onChange={(event) =>
                          updateRemoteHeader(remote.id, header.id, { secret: event.target.checked })
                        }
                        type="checkbox"
                      />
                      Secret
                    </label>
                    <Button
                      aria-label={`Remove header ${header.name || "without a name"}`}
                      onClick={() =>
                        updateRemote(remote.id, {
                          headers: remote.headers.filter((item) => item.id !== header.id),
                        })
                      }
                      size="icon"
                      type="button"
                      variant="outline"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
  );
}

type PackageTargetsSectionProps = {
  packages: PackageTarget[];
  setPackages: Dispatch<SetStateAction<PackageTarget[]>>;
  updatePackage: (id: string, patch: Partial<PackageTarget>) => void;
  updatePackageArgument: (
    packageId: string,
    argumentId: string,
    patch: Partial<PackageArgumentField>
  ) => void;
  updatePackageEnvironment: (
    packageId: string,
    environmentId: string,
    patch: Partial<EnvironmentField>
  ) => void;
};

export function PackageTargetsSection({
  packages,
  setPackages,
  updatePackage,
  updatePackageArgument,
  updatePackageEnvironment,
}: PackageTargetsSectionProps) {
  return (
      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <CardTitle>Package Targets</CardTitle>
          <Button onClick={() => setPackages((current) => [...current, emptyPackage()])} type="button" variant="outline">
            <Plus className="size-4" />
            Add package
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          {packages.map((packageTarget, index) => (
            <div className="space-y-4 rounded-md border p-4" key={packageTarget.id}>
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">Package {index + 1}</div>
                <Button
                  aria-label={`Remove package ${packageTarget.identifier || index + 1}`}
                  onClick={() =>
                    setPackages((current) => current.filter((item) => item.id !== packageTarget.id))
                  }
                  size="icon"
                  type="button"
                  variant="outline"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
              <div className="grid gap-4 md:grid-cols-[180px_minmax(0,1fr)_160px]">
                <div className="grid gap-2">
                  <Label htmlFor={`${packageTarget.id}-registry`}>Runtime</Label>
                  <Select
                    onValueChange={(value) =>
                      updatePackage(packageTarget.id, { registryType: value })
                    }
                    value={packageTarget.registryType}
                  >
                    <SelectTrigger id={`${packageTarget.id}-registry`}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {PACKAGE_RUNTIME_OPTIONS.map((option) => (
                        <SelectItem key={option.value} value={option.value}>
                          {option.label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="grid gap-2">
                  <Label htmlFor={`${packageTarget.id}-identifier`}>Package</Label>
                  <Input
                    id={`${packageTarget.id}-identifier`}
                    onChange={(event) =>
                      updatePackage(packageTarget.id, { identifier: event.target.value })
                    }
                    placeholder="@scope/package"
                    value={packageTarget.identifier}
                  />
                </div>
                <div className="grid gap-2">
                  <Label htmlFor={`${packageTarget.id}-version`}>Version</Label>
                  <Input
                    id={`${packageTarget.id}-version`}
                    onChange={(event) =>
                      updatePackage(packageTarget.id, { version: event.target.value })
                    }
                    value={packageTarget.version}
                  />
                </div>
              </div>
              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="text-sm font-medium">Environment Variables</div>
                  <Button
                    onClick={() =>
                      updatePackage(packageTarget.id, {
                        environmentVariables: [
                          ...packageTarget.environmentVariables,
                          emptyEnvironment(),
                        ],
                      })
                    }
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    <Plus className="size-4" />
                    Add variable
                  </Button>
                </div>
                {packageTarget.environmentVariables.map((envVar) => (
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1.5fr)_minmax(0,1fr)_140px_auto_auto_auto]" key={envVar.id}>
                    <Input
                      onChange={(event) =>
                        updatePackageEnvironment(packageTarget.id, envVar.id, {
                          name: event.target.value,
                        })
                      }
                      placeholder="Variable name"
                      value={envVar.name}
                    />
                    <Input
                      onChange={(event) =>
                        updatePackageEnvironment(packageTarget.id, envVar.id, {
                          description: event.target.value,
                        })
                      }
                      placeholder="Description"
                      value={envVar.description}
                    />
                    <Input
                      onChange={(event) =>
                        updatePackageEnvironment(packageTarget.id, envVar.id, {
                          defaultValue: event.target.value,
                        })
                      }
                      placeholder="Default"
                      value={envVar.defaultValue}
                    />
                    <Select
                      onValueChange={(value) =>
                        updatePackageEnvironment(packageTarget.id, envVar.id, {
                          format: value,
                        })
                      }
                      value={envVar.format}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {PACKAGE_ARGUMENT_FORMAT_OPTIONS.map((option) => (
                          <SelectItem key={option.value} value={option.value}>
                            {option.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        checked={envVar.required}
                        onChange={(event) =>
                          updatePackageEnvironment(packageTarget.id, envVar.id, {
                            required: event.target.checked,
                          })
                        }
                        type="checkbox"
                      />
                      Required
                    </label>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        checked={envVar.secret}
                        onChange={(event) =>
                          updatePackageEnvironment(packageTarget.id, envVar.id, {
                            secret: event.target.checked,
                          })
                        }
                        type="checkbox"
                      />
                      Secret
                    </label>
                    <Button
                      aria-label={`Remove environment variable ${envVar.name || "without a name"}`}
                      onClick={() =>
                        updatePackage(packageTarget.id, {
                          environmentVariables: packageTarget.environmentVariables.filter(
                            (item) => item.id !== envVar.id
                          ),
                        })
                      }
                      size="icon"
                      type="button"
                      variant="outline"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                ))}
              </div>
              <div className="space-y-3 border-t pt-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium">Runtime Arguments</div>
                    <div className="text-xs text-muted-foreground">
                      Define static process arguments or user-configurable flags shown during setup.
                    </div>
                  </div>
                  <Button
                    onClick={() =>
                      updatePackage(packageTarget.id, {
                        packageArguments: [
                          ...packageTarget.packageArguments,
                          emptyPackageArgument(),
                        ],
                      })
                    }
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    <Plus className="size-4" />
                    Add argument
                  </Button>
                </div>
                {packageTarget.packageArguments.map((argument) => (
                  <div className="space-y-3 rounded-md border p-3" key={argument.id}>
                    <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)_140px_auto]">
                      <Input
                        onChange={(event) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            name: event.target.value,
                          })
                        }
                        placeholder="Config key, e.g. SERVER_LOG_LEVEL"
                        value={argument.name}
                      />
                      <Input
                        onChange={(event) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            flag: event.target.value,
                          })
                        }
                        placeholder="Flag, e.g. --log-level"
                        value={argument.flag}
                      />
                      <Input
                        onChange={(event) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            value: event.target.value,
                          })
                        }
                        placeholder="Static value, e.g. stdio"
                        value={argument.value}
                      />
                      <Select
                        onValueChange={(value) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            format: value,
                          })
                        }
                        value={argument.format}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {PACKAGE_ARGUMENT_FORMAT_OPTIONS.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                              {option.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        aria-label={`Remove runtime argument ${argument.name || "without a name"}`}
                        onClick={() =>
                          updatePackage(packageTarget.id, {
                            packageArguments: packageTarget.packageArguments.filter(
                              (item) => item.id !== argument.id
                            ),
                          })
                        }
                        size="icon"
                        type="button"
                        variant="outline"
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                    <div className="grid gap-3 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)_minmax(0,1fr)_auto_auto]">
                      <Input
                        onChange={(event) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            description: event.target.value,
                          })
                        }
                        placeholder="Description"
                        value={argument.description}
                      />
                      <Input
                        onChange={(event) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            defaultValue: event.target.value,
                          })
                        }
                        placeholder="Default"
                        value={argument.defaultValue}
                      />
                      <Input
                        onChange={(event) =>
                          updatePackageArgument(packageTarget.id, argument.id, {
                            options: event.target.value,
                          })
                        }
                        placeholder="Options, comma-separated"
                        value={argument.options}
                      />
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          checked={argument.required}
                          onChange={(event) =>
                            updatePackageArgument(packageTarget.id, argument.id, {
                              required: event.target.checked,
                            })
                          }
                          type="checkbox"
                        />
                        Required
                      </label>
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          checked={argument.secret}
                          onChange={(event) =>
                            updatePackageArgument(packageTarget.id, argument.id, {
                              secret: event.target.checked,
                            })
                          }
                          type="checkbox"
                        />
                        Secret
                      </label>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
  );
}
