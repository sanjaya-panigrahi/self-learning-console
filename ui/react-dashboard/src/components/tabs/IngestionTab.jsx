export default function IngestionTab({ text, loading, files, ingestionStatus, Badge }) {
  const liveRunning = ingestionStatus?.state === 'running'
  const processedFiles = Number(ingestionStatus?.processed_files || files.length || 0)
  const totalFiles = Number(ingestionStatus?.total_files || 0)

  return (
    <section className="panel-grid panel-grid-ingestion">
      <section className="panel panel-wide">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{text.ingestion.ledger}</p>
            <h3>{text.ingestion.processedFiles}</h3>
            <p className="meta-line">
              {liveRunning
                ? `Indexing in progress: ${processedFiles}${totalFiles > 0 ? ` / ${totalFiles}` : ''} files, ${Number(ingestionStatus?.indexed_chunks || 0)} chunks.`
                : `Last run state: ${ingestionStatus?.state || 'idle'}`}
            </p>
          </div>
          <span>{loading ? text.ingestion.refreshing : `${files.length} ${text.ingestion.rowsSuffix}`}</span>
        </div>
        <div className="table-wrap scroll-region scroll-region-table">
          <table>
            <thead>
              <tr>
                <th>{text.ingestion.table.file}</th>
                <th>{text.ingestion.table.status}</th>
                <th>{text.ingestion.table.chunks}</th>
                <th>{text.ingestion.table.method}</th>
                <th>{text.ingestion.table.ocr}</th>
                <th>{text.ingestion.table.piiFindings}</th>
                <th>{text.ingestion.table.approval}</th>
                <th>{text.ingestion.table.reason}</th>
              </tr>
            </thead>
            <tbody>
              {files.length === 0 && (
                <tr>
                  <td colSpan="8" className="empty-state">{text.ingestion.table.noRecords}</td>
                </tr>
              )}
              {files.map((item) => (
                <tr key={item.file} className={item.status === 'duplicate' ? 'row-duplicate' : ''}>
                  <td title={item.duplicate_of ? `Duplicate of: ${item.duplicate_of}` : undefined}>{item.file}</td>
                  <td><Badge value={item.status} /></td>
                  <td>{Number(item.indexed_chunks || 0)}</td>
                  <td>{item.ingestion_method || '-'}</td>
                  <td>
                    {item.file?.toLowerCase()?.endsWith('.pdf')
                      ? (item.ocr_used ? `Yes (${item.ocr_pages || 0}p)` : 'No')
                      : '-'}
                  </td>
                  <td>
                    {(item.pii_findings || []).length === 0 ? '-' : (item.pii_findings || []).map((finding) => (
                      <div key={`${item.file}-${finding.type}`} className="finding-line">
                        {finding.type} ({finding.severity}) {finding.sample}
                      </div>
                    ))}
                  </td>
                  <td>
                    {item.approval
                      ? `${item.approval.approved_by}: ${item.approval.reason}`
                      : '-'}
                  </td>
                  <td>{item.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  )
}
