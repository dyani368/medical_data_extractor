import type { DocumentSummary, DocumentDetail, Extraction, Message, Passage } from './types'

const cardio = 'Cardiovascular follow-up.pdf'
const adverse = 'Adverse event report.pdf'
const project = 'Q2 service reliability review.pdf'
export const demoDocuments: DocumentSummary[] = [
  { document_id: 'demo-project', filename: project, created_at: '2026-10-12T10:00:00Z', chunk_count: 4, successful_extractions: 4, failed_extractions: 0, extraction_status: 'succeeded' },
  { document_id: 'demo-cardio', filename: cardio, created_at: '2026-10-12T09:30:00Z', chunk_count: 3, successful_extractions: 3, failed_extractions: 0, extraction_status: 'succeeded' },
  { document_id: 'demo-adverse', filename: adverse, created_at: '2026-10-12T09:15:00Z', chunk_count: 2, successful_extractions: 2, failed_extractions: 0, extraction_status: 'succeeded' },
]
export const demoDetails: Record<string, DocumentDetail> = {
  'demo-project': { document_id: 'demo-project', filename: project, created_at: demoDocuments[0].created_at, page_count: 1, pages: [{ page_number: 1, width: 612, height: 792 }], chunks: [
    { id: 106, chunk_index: 0, page_number: 1, element_type: 'text', section_title: 'Overview', bbox: [54, 176, 555, 261], content: 'The Atlas service handled 1.8 million requests during Q2. Availability was 99.93%, below the 99.95% quarterly target. The largest incident was a 37-minute outage on May 14.' },
    { id: 107, chunk_index: 1, page_number: 1, element_type: 'text', section_title: 'Incident review', bbox: [54, 287, 555, 371], content: 'A database connection pool limit caused the May 14 outage. The team increased the pool limit, added connection saturation alerts, and tested the fix under peak traffic.' },
    { id: 108, chunk_index: 2, page_number: 1, element_type: 'table', section_title: 'Quarterly measures', bbox: [55, 426, 556, 548], content: '| Measure | Result | Target |\n| --- | --- | --- |\n| Availability | 99.93% | 99.95% |\n| Requests | 1.8 million | 1.5 million |\n| P95 latency | 182 ms | 200 ms |' },
    { id: 109, chunk_index: 3, page_number: 1, element_type: 'text', section_title: 'Next steps', bbox: [54, 590, 555, 655], content: 'Run a monthly saturation test and review alert thresholds. Owner: Platform Engineering. Due date: July 15, 2026.' },
  ] },
  'demo-cardio': { document_id: 'demo-cardio', filename: cardio, created_at: demoDocuments[1].created_at, page_count: 1, pages: [{ page_number: 1, width: 612, height: 792 }], chunks: [
    { id: 101, chunk_index: 0, page_number: 1, element_type: 'text', section_title: 'Presenting concern', bbox: [55, 219, 555, 271], content: 'A 44-year-old adult reports mild dizziness during the last week. The patient denies chest pain and shortness of breath. A fictional blood pressure reading at this visit is 160/95 mmHg.' },
    { id: 102, chunk_index: 1, page_number: 1, element_type: 'text', section_title: 'Assessment and plan', bbox: [55, 280, 555, 391], content: 'Elevated blood pressure is noted in this synthetic scenario. The text is educational sample content and is not medical advice.\nThe fictional plan lists Lisinopril 10 mg once daily and follow-up in two weeks.' },
    { id: 103, chunk_index: 2, page_number: 1, element_type: 'text', section_title: 'Clinical note', bbox: [55, 367, 555, 402], content: 'Any real treatment decision must be made by a qualified clinician using the actual patient’s complete medical record.' },
  ] },
  'demo-adverse': { document_id: 'demo-adverse', filename: adverse, created_at: demoDocuments[2].created_at, page_count: 1, pages: [{ page_number: 1, width: 612, height: 792 }], chunks: [
    { id: 104, chunk_index: 0, page_number: 1, element_type: 'text', section_title: 'Event summary', bbox: [55, 219, 555, 274], content: 'In this synthetic scenario, the patient reports nausea and a mild headache beginning the day after starting the fictional study medication DemoDrug 25 mg.' },
    { id: 105, chunk_index: 1, page_number: 1, element_type: 'text', section_title: 'Outcome and follow-up', bbox: [55, 280, 555, 391], content: 'The event is described as mild. No emergency care was needed and symptoms resolved within 24 hours after the study medication was held. The investigator plans a follow-up call in seven days.' },
  ] },
}
const projectFindings: Record<number, { summary: string; key_entities: Record<string, unknown> }> = {
  106: { summary: 'Traffic exceeded the plan, but availability missed its target following a May outage.', key_entities: { requests: '1.8 million', availability: '99.93%', target: '99.95%', largest_outage: '37 minutes' } },
  107: { summary: 'The outage was attributed to a database pool limit. The team raised the limit and added alerts.', key_entities: { cause: 'Database connection pool limit', corrective_action: 'Increase limit and add saturation alerts' } },
  108: { summary: 'Availability missed its target by 0.02 percentage points. P95 latency was within target.', key_entities: { availability: '99.93% vs 99.95% target', requests: '1.8 million', p95_latency: '182 ms vs 200 ms target' } },
  109: { summary: 'Platform Engineering will test saturation monthly and review alert thresholds.', key_entities: { owner: 'Platform Engineering', due_date: 'July 15, 2026' } },
}
export const demoExtractions: Record<string, Extraction> = Object.fromEntries(Object.entries(demoDetails).map(([id, document]) => [id, {
  document_id: id, filename: document.filename, items: document.chunks.map((chunk, index) => ({
    document_id: chunk.id, chunk_index: chunk.chunk_index, page_number: chunk.page_number, status: 'succeeded', error_type: null,
    result: { summary: id === 'demo-project' ? projectFindings[chunk.id].summary : index === 0 ? (id === 'demo-cardio' ? 'Follow-up record notes mild dizziness and blood pressure of 160/95 mmHg; chest pain and shortness of breath were denied.' : 'Nausea and a mild headache began after the study medication was started.') : id === 'demo-cardio' ? (index === 1 ? 'Elevated blood pressure was noted. The fictional plan lists medication and follow-up in two weeks.' : 'Treatment decisions require review of the complete clinical record.') : 'The event was mild, resolved within 24 hours after medication was held, and a call was planned for seven days later.',
      category: id === 'demo-project' ? 'Operations Report' : id === 'demo-cardio' ? 'Case Report' : 'Adverse Event',
      key_entities: id === 'demo-project' ? projectFindings[chunk.id].key_entities : index === 0 ? (id === 'demo-cardio' ? { symptom: 'Mild dizziness', blood_pressure: '160/95 mmHg', chest_pain: 'Denied', shortness_of_breath: 'Denied' } : { symptoms: ['Nausea', 'Mild headache'], medication: 'DemoDrug', dose: '25 mg' }) : id === 'demo-cardio' && index === 1 ? { follow_up: 'Two weeks', medication: 'Lisinopril 10 mg' } : id === 'demo-adverse' ? { severity: 'Mild', resolution: 'Within 24 hours', follow_up: 'Seven days' } : {}, confidence: 0.94 },
  })),
}]))
export const demoMessages: Message[] = [
  { id: 'demo-user', role: 'user', content: 'What symptom and blood pressure were recorded in the cardiovascular follow-up?' },
  { id: 'demo-assistant', role: 'assistant', content: 'The cardiovascular follow-up recorded **mild dizziness** during the previous week and a blood pressure of **160/95 mmHg**. The patient denied chest pain and shortness of breath. [doc:101]', sources: [{ document_id: 101, filename: cardio, page_number: 1 }] },
]
export function demoPassage(id: number): Passage | undefined {
  for (const document of Object.values(demoDetails)) {
    const chunk = document.chunks.find(chunk => chunk.id === id)
    if (chunk) return { ...chunk, filename: document.filename, source_document_id: document.document_id }
  }
}
