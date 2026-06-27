import { useEffect, useRef, useState } from "react";
import { deleteDocument, fetchDocuments, uploadDocument, type RagDocument } from "../api";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const FILE_ICON: Record<string, string> = {
  pdf: "📄", docx: "📝", xlsx: "📊", txt: "🗒️",
};

export default function DocumentPanel() {
  const [docs, setDocs] = useState<RagDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetchDocuments().then(setDocs).catch(() => {});
  }, []);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploading(true);
    setError("");
    for (const file of Array.from(files)) {
      try {
        const doc = await uploadDocument(file);
        setDocs((prev) => [doc as any, ...prev]);
      } catch (err: any) {
        setError(err.message || "Upload failed");
      }
    }
    setUploading(false);
  }

  async function handleDelete(docId: string) {
    await deleteDocument(docId);
    setDocs((prev) => prev.filter((d) => d.id !== docId));
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); handleFiles(e.dataTransfer.files); }}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-xl border-2 border-dashed px-4 py-5 text-center transition-colors ${
          dragOver
            ? "border-brand-500 bg-brand-950/30"
            : "border-slate-700 hover:border-slate-500"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.csv"
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
        {uploading ? (
          <p className="text-xs text-brand-400 font-medium">Uploading…</p>
        ) : (
          <>
            <p className="text-xs font-semibold text-slate-300">Drop files here or click to upload</p>
            <p className="mt-0.5 text-[10px] text-slate-500">PDF · DOCX · XLSX · TXT · CSV — max 20 MB</p>
          </>
        )}
      </div>

      {error && (
        <p className="rounded-lg border border-red-800/40 bg-red-950/20 px-3 py-2 text-xs text-red-400">
          {error}
        </p>
      )}

      {/* Document list */}
      {docs.length === 0 ? (
        <p className="text-center text-[11px] text-slate-600">No documents uploaded yet.</p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {docs.map((doc) => (
            <div
              key={doc.id}
              className="group flex items-center gap-2 rounded-lg border border-slate-700/50 bg-slate-800/40 px-3 py-2"
            >
              <span className="text-base">{FILE_ICON[doc.file_type] ?? "📎"}</span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs font-medium text-slate-200">{doc.filename}</p>
                <p className="text-[10px] text-slate-500">
                  {formatSize(doc.file_size)} · {doc.chunk_count} chunks
                </p>
              </div>
              <button
                onClick={() => handleDelete(doc.id)}
                title="Remove document"
                className="hidden rounded p-1 text-slate-600 hover:bg-red-950/40 hover:text-red-400 group-hover:flex"
              >
                <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
