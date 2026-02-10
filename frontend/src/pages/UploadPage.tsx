import { useState, useRef, type DragEvent, type ChangeEvent } from "react";
import { useNavigate } from "react-router-dom";
import apiClient from "@/api/client";

export default function UploadPage() {
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const upload = async (file: File) => {
    setError(null);
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setError("Only PDF files are accepted.");
      return;
    }
    setUploading(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const resp = await apiClient.post("/invoices/upload", form);
      navigate(`/invoices/${resp.data.id}`);
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { error?: string } } })?.response?.data
          ?.error ?? "Upload failed";
      setError(msg);
    } finally {
      setUploading(false);
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) upload(file);
  };

  const onFileChange = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) upload(file);
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
        onClick={() => fileRef.current?.click()}
      >
        <div className="icon">+</div>
        {uploading ? (
          <p>Uploading and parsing...</p>
        ) : (
          <>
            <p>
              <strong>Drag &amp; drop</strong> a PDF here, or click to browse
            </p>
            <p>Supports supplier invoice PDFs up to 20 MB</p>
          </>
        )}
      </div>

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
