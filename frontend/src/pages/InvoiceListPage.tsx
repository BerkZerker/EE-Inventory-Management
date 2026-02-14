import { useState, useEffect, useRef, type DragEvent, type ChangeEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { AxiosError } from "axios";
import { invoiceApi } from "@/api/services";
import { extractErrorMessage } from "@/api/errors";
import type { Invoice } from "@/types";

export default function InvoiceListPage() {
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");

  // Upload state
  const [showUpload, setShowUpload] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const resp = await invoiceApi.list(statusFilter || undefined);
        setInvoices(resp.data);
      } catch (err) {
        setError(extractErrorMessage(err, "Failed to load invoices"));
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [statusFilter]);

  const toggleUpload = () => {
    if (showUpload) {
      setSelectedFile(null);
      setUploadError(null);
      setDragOver(false);
      if (fileRef.current) fileRef.current.value = "";
    }
    setShowUpload(!showUpload);
  };

  const selectFile = (file: File) => {
    setUploadError(null);
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setUploadError("Only PDF files are accepted.");
      return;
    }
    setSelectedFile(file);
  };

  const clearFile = () => {
    setSelectedFile(null);
    setUploadError(null);
    if (fileRef.current) fileRef.current.value = "";
  };

  const submit = async (overwrite = false) => {
    if (!selectedFile) return;
    setUploadError(null);
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
        setUploadError(resp.data?.error ?? "Upload failed");
      } else {
        setUploadError("Upload failed");
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
        <h2>Invoices</h2>
        <p>View and manage supplier invoices.</p>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div className="toolbar">
        <button className="primary" onClick={toggleUpload}>
          {showUpload ? "Cancel Upload" : "Upload Invoice"}
        </button>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>

      {showUpload && (
        <div style={{ marginBottom: "1.5rem" }}>
          {uploadError && <div className="error-message">{uploadError}</div>}

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
      )}

      {loading ? (
        <div className="loading">Loading...</div>
      ) : invoices.length === 0 ? (
        <div className="empty-state">
          <p>No invoices found.</p>
        </div>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Reference</th>
              <th>Supplier</th>
              <th>Date</th>
              <th>Total</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv) => (
              <tr key={inv.id}>
                <td>
                  <Link to={`/invoices/${inv.id}`}>{inv.invoice_ref}</Link>
                </td>
                <td>{inv.supplier}</td>
                <td>{inv.invoice_date}</td>
                <td>
                  {inv.total_amount != null
                    ? `$${inv.total_amount.toFixed(2)}`
                    : "-"}
                </td>
                <td>
                  <span className={`badge ${inv.status}`}>{inv.status}</span>
                </td>
                <td>{new Date(inv.created_at).toLocaleDateString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
