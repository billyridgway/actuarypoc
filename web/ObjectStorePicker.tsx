import React from "react";

// Object-store source picker (docs/workspace-sources.md): the primary
// way to populate a new workspace on Roost. The user browses buckets
// the app's store identity can see, descends by prefix, and selects
// files — individually, or a whole prefix at once. The workspace
// records references to the chosen objects (bucket + key + etag at
// selection); the bytes are never copied into the workspace.

interface StoreBucket {
  name: string;
  createdAt?: string | null;
}

interface StoreEntry {
  key: string;
  isPrefix: boolean;
  size?: number | null;
  lastModified?: string | null;
  etag?: string | null;
}

interface ObjectsResponse {
  bucket: string;
  prefix: string;
  entries: StoreEntry[];
  truncated: boolean;
}

interface PrefixSelection {
  bucket: string;
  prefix: string;
  count: number;
  size: number;
}

const formatSize = (value?: number | null): string => {
  if (value == null) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
};

interface ObjectStorePickerProps {
  onCreated: (workspaceId: string) => void;
  onCancel: () => void;
}

export const ObjectStorePicker: React.FC<ObjectStorePickerProps> = ({ onCreated, onCancel }) => {
  const [buckets, setBuckets] = React.useState<StoreBucket[]>([]);
  const [bucket, setBucket] = React.useState<string>("");
  const [prefix, setPrefix] = React.useState<string>("");
  const [entries, setEntries] = React.useState<StoreEntry[]>([]);
  const [truncated, setTruncated] = React.useState<boolean>(false);
  const [loading, setLoading] = React.useState<boolean>(false);
  const [error, setError] = React.useState<string | null>(null);
  const [creating, setCreating] = React.useState<boolean>(false);
  // Explicitly checked files, by "bucket\0key".
  const [checked, setChecked] = React.useState<Map<string, { bucket: string; key: string; size: number }>>(
    new Map(),
  );
  const [prefixSelections, setPrefixSelections] = React.useState<PrefixSelection[]>([]);

  const loadBuckets = React.useCallback(async () => {
    try {
      const resp = await fetch("/api/object-store/buckets");
      if (!resp.ok) throw new Error((await resp.text()) || `HTTP ${resp.status}`);
      const body = await resp.json();
      const list: StoreBucket[] = Array.isArray(body.buckets) ? body.buckets : [];
      setBuckets(list);
      if (list.length > 0) setBucket((prev) => prev || list[0].name);
    } catch (err: any) {
      setError(err?.message || "Failed to list buckets.");
    }
  }, []);

  React.useEffect(() => {
    void loadBuckets();
  }, [loadBuckets]);

  const loadObjects = React.useCallback(async () => {
    if (!bucket) return;
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ bucket, prefix });
      const resp = await fetch(`/api/object-store/objects?${params.toString()}`);
      if (!resp.ok) throw new Error((await resp.text()) || `HTTP ${resp.status}`);
      const body: ObjectsResponse = await resp.json();
      setEntries(Array.isArray(body.entries) ? body.entries : []);
      setTruncated(Boolean(body.truncated));
    } catch (err: any) {
      setError(err?.message || "Failed to list objects.");
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [bucket, prefix]);

  React.useEffect(() => {
    void loadObjects();
  }, [loadObjects]);

  const coveredByPrefix = (key: string): boolean =>
    prefixSelections.some((sel) => sel.bucket === bucket && key.startsWith(sel.prefix));

  const toggleFile = (entry: StoreEntry) => {
    const id = `${bucket}\u0000${entry.key}`;
    setChecked((prev) => {
      const next = new Map(prev);
      if (next.has(id)) next.delete(id);
      else next.set(id, { bucket, key: entry.key, size: entry.size ?? 0 });
      return next;
    });
  };

  const selectAllInPrefix = async () => {
    try {
      const params = new URLSearchParams({ bucket, prefix, recursive: "true" });
      const resp = await fetch(`/api/object-store/objects?${params.toString()}`);
      if (!resp.ok) throw new Error((await resp.text()) || `HTTP ${resp.status}`);
      const body: ObjectsResponse = await resp.json();
      const files = (body.entries || []).filter((e) => !e.isPrefix);
      if (files.length === 0) {
        setError("No files under this prefix.");
        return;
      }
      setPrefixSelections((prev) => [
        ...prev.filter((sel) => !(sel.bucket === bucket && sel.prefix === prefix)),
        {
          bucket,
          prefix,
          count: files.length,
          size: files.reduce((sum, e) => sum + (e.size ?? 0), 0),
        },
      ]);
      // Individual checks under the prefix are subsumed by it.
      setChecked((prev) => {
        const next = new Map(prev);
        for (const [id, sel] of next) {
          if (sel.bucket === bucket && sel.key.startsWith(prefix)) next.delete(id);
        }
        return next;
      });
    } catch (err: any) {
      setError(err?.message || "Failed to enumerate the prefix.");
    }
  };

  const removePrefixSelection = (sel: PrefixSelection) => {
    setPrefixSelections((prev) =>
      prev.filter((s) => !(s.bucket === sel.bucket && s.prefix === sel.prefix)),
    );
  };

  const totalCount =
    checked.size + prefixSelections.reduce((sum, sel) => sum + sel.count, 0);
  const totalSize =
    Array.from(checked.values()).reduce((sum, sel) => sum + sel.size, 0) +
    prefixSelections.reduce((sum, sel) => sum + sel.size, 0);

  const create = async () => {
    setCreating(true);
    setError(null);
    try {
      const byBucket = new Map<string, string[]>();
      for (const sel of checked.values()) {
        const list = byBucket.get(sel.bucket) ?? [];
        list.push(sel.key);
        byBucket.set(sel.bucket, list);
      }
      const sources: Array<{ bucket: string; keys?: string[]; prefix?: string }> = [
        ...Array.from(byBucket.entries()).map(([b, keys]) => ({ bucket: b, keys })),
        ...prefixSelections.map((sel) => ({ bucket: sel.bucket, prefix: sel.prefix })),
      ];
      const resp = await fetch("/api/workspaces", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sources }),
      });
      if (!resp.ok) throw new Error((await resp.text()) || `HTTP ${resp.status}`);
      const body = await resp.json();
      const workspaceId = body?.workspace?.id;
      if (!workspaceId) throw new Error("Workspace ID was not returned from create endpoint.");
      onCreated(String(workspaceId));
    } catch (err: any) {
      setError(err?.message || "Failed to create workspace from the selected sources.");
    } finally {
      setCreating(false);
    }
  };

  const crumbs: Array<{ label: string; prefix: string }> = [{ label: bucket || "bucket", prefix: "" }];
  prefix
    .split("/")
    .filter(Boolean)
    .forEach((segment, index, all) => {
      crumbs.push({ label: segment, prefix: all.slice(0, index + 1).join("/") + "/" });
    });

  return (
    <div className="source-picker">
      <h3>Choose from the object store</h3>
      <p className="muted">
        Pick a whole bucket prefix or individual files. The workspace references the objects in
        place — nothing is copied — and pins each object's version when you create it.
      </p>
      <p>
        <label>
          Bucket{" "}
          <select
            value={bucket}
            onChange={(e) => {
              setBucket(e.target.value);
              setPrefix("");
            }}
          >
            {buckets.map((b) => (
              <option key={b.name} value={b.name}>
                {b.name}
              </option>
            ))}
          </select>
        </label>
      </p>
      <p className="muted source-picker__crumbs">
        {crumbs.map((crumb, index) => (
          <span key={crumb.prefix || "root"}>
            {index > 0 && " / "}
            <a
              href="#"
              onClick={(event) => {
                event.preventDefault();
                setPrefix(crumb.prefix);
              }}
            >
              {crumb.label}
            </a>
          </span>
        ))}
      </p>
      {error && <p className="error">{error}</p>}
      {loading ? (
        <p className="muted">Listing objects…</p>
      ) : (
        <table className="kv-table source-picker__table">
          <tbody>
            {entries.map((entry) =>
              entry.isPrefix ? (
                <tr key={entry.key}>
                  <td>
                    <a
                      href="#"
                      onClick={(event) => {
                        event.preventDefault();
                        setPrefix(entry.key);
                      }}
                    >
                      {entry.key.slice(prefix.length)} ▸
                    </a>
                  </td>
                  <td className="muted">prefix</td>
                  <td />
                </tr>
              ) : (
                <tr key={entry.key}>
                  <td>
                    <label>
                      <input
                        type="checkbox"
                        disabled={coveredByPrefix(entry.key)}
                        checked={
                          coveredByPrefix(entry.key) ||
                          checked.has(`${bucket}\u0000${entry.key}`)
                        }
                        onChange={() => toggleFile(entry)}
                      />{" "}
                      {entry.key.slice(prefix.length)}
                    </label>
                  </td>
                  <td>{formatSize(entry.size)}</td>
                  <td className="muted">{entry.lastModified ?? ""}</td>
                </tr>
              ),
            )}
            {entries.length === 0 && (
              <tr>
                <td className="muted">Nothing under this prefix.</td>
                <td />
                <td />
              </tr>
            )}
          </tbody>
        </table>
      )}
      {truncated && (
        <p className="muted">Listing truncated — descend into a prefix to see more.</p>
      )}
      <p>
        <button type="button" className="button button-secondary" onClick={() => void selectAllInPrefix()}>
          Select all in this prefix
        </button>
      </p>
      {(prefixSelections.length > 0 || checked.size > 0) && (
        <div className="source-picker__summary">
          <strong>Selected:</strong> {totalCount} file{totalCount === 1 ? "" : "s"} ·{" "}
          {formatSize(totalSize)}
          <ul className="muted">
            {prefixSelections.map((sel) => (
              <li key={`${sel.bucket}/${sel.prefix}`}>
                {sel.bucket}/{sel.prefix} — all {sel.count} files (resolved at creation){" "}
                <a
                  href="#"
                  onClick={(event) => {
                    event.preventDefault();
                    removePrefixSelection(sel);
                  }}
                >
                  remove
                </a>
              </li>
            ))}
            {Array.from(checked.values()).map((sel) => (
              <li key={`${sel.bucket}\u0000${sel.key}`}>
                {sel.bucket}/{sel.key}
              </li>
            ))}
          </ul>
        </div>
      )}
      <p>
        <button type="button" className="button" disabled={creating || totalCount === 0} onClick={() => void create()}>
          {creating ? "Creating…" : "Create workspace from selected files"}
        </button>{" "}
        <button type="button" className="button button-secondary" disabled={creating} onClick={onCancel}>
          Cancel
        </button>
      </p>
    </div>
  );
};

export default ObjectStorePicker;
