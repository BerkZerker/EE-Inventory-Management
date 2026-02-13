import { useState, useRef, type DragEvent, type ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import { invoiceApi } from "@/api/services";

export default function UploadPage() {
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const selectFile = (file: File) => {
    setError(null);
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF files are accepted.");
      return;
    }
    setSelectedFile(file);
  };

  const clearFile = () => {
    setSelectedFile(null);
    setError(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const submit = async (overwrite = false) => {
    if (!selectedFile) return;
    setError(null);
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      if (overwrite) formData.append("overwrite", "true");
      const resp = await invoiceApi.upload(formData);
      navigate(`/invoices/${resp.data.id}`);
    } catch (err: unknown) {
      if (err instanceof AxiosError && err.response) {
        const resp = err.response;
        if (resp.status === 409 && resp.data?.details?.can_overwrite) {
          if (confirm(`${resp.data.error}\n\nOverwrite the existing pending invoice?`)) {
            setUploading(false);
            submit(true);
            return;
          }
        }
        setError(resp.data?.error ?? "Upload failed");
      } else {
        setError("Upload failed");
      }
    } finally {
      setUploading(false);
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) selectFile(file);
  };

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) selectFile(file);
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div>
      <div className="page-header">
        <h2>Upload Invoice</h2>
        <p>Upload a supplier invoice PDF for AI-powered parsing.</p>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div
        className={`upload-zone${dragOver ? " drag-over" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => !selectedFile && !uploading && fileRef.current?.click()}
        style={selectedFile ? { cursor: "default" } : undefined}
      >
        {selectedFile ? (
          <div>
            <div className="icon">&#128196;</div>
            <p>
              <strong>{selectedFile.name}</strong>
            </p>
            <p>{formatSize(selectedFile.size)}</p>
            {!uploading && (
              <button
                style={{ marginTop: "0.75rem" }}
                onClick={(e) => {
                  e.stopPropagation();
                  clearFile();
                }}
              >
                Clear
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="icon">+</div>
            <p>
              <strong>Drag &amp; drop</strong> a PDF here, or click to browse
            </p>
            <p>Supports supplier invoice PDFs up to 20 MB</p>
          </>
        )}
      </div>

      {selectedFile && (
        <div style={{ marginTop: "1rem", textAlign: "center" }}>
          <button
            className="primary"
            disabled={uploading}
            onClick={() => submit()}
            style={{ minWidth: "200px", padding: "0.75em 1.5em" }}
          >
            {uploading ? (
              <span>
                <span className="spinner" /> Parsing invoice with AI...
              </span>
            ) : (
              "Submit for Processing"
            )}
          </button>
        </div>
      )}

      <input
        ref={fileRef}
        type="file"
        accept=".pdf"
        style={{ display: "none" }}
        onChange={onFileChange}
      />
    </div>
  );
}
