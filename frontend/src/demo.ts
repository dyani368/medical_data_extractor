import type { DocumentSummary, DocumentDetail, Extraction, Message, Passage } from './types'

const cardio = 'Cardiovascular follow-up.pdf'
const adverse = 'Adverse event report.pdf'
export const demoDocuments: DocumentSummary[] = [
  { document_id: 'demo-cardio', filename: cardio, created_at: '2026-10-12T09:30:00Z', chunk_count: 3, successful_extractions: 3, failed_extractions: 0, extraction_status: 'succeeded' },
  { document_id: 'demo-adverse', filename: adverse, created_at: '2026-10-12T09:15:00Z', chunk_count: 2, successful_extractions: 2, failed_extractions: 0, extraction_status: 'succeeded' },
]
export const demoDetails: Record<string, DocumentDetail> = {
  'demo-cardio': { document_id: 'demo-cardio', filename: cardio, created_at: demoDocuments[0].created_at, chunks: [
    { id: 101, chunk_index: 0, page_number: 1, content: 'Cardiovascular follow-up\nPresenting concern: An adult reports mild dizziness during the last week. The patient denies chest pain and shortness of breath. Blood pressure at this visit is 160/95 mmHg.' },
    { id: 102, chunk_index: 1, page_number: 1, content: 'Assessment: Elevated blood pressure is noted.\nPlan: The fictional plan lists medication 10 mg once daily and follow-up in two weeks. This sample is educational content, not medical advice.' },
    { id: 103, chunk_index: 2, page_number: 1, content: 'Any real treatment decision must be made by a qualified clinician using the actual patient’s complete medical record. This is an invented example for a software demonstration.' },
  ] },
  'demo-adverse': { document_id: 'demo-adverse', filename: adverse, created_at: demoDocuments[1].created_at, chunks: [
    { id: 104, chunk_index: 0, page_number: 1, content: 'Adverse event report\nThe participant reports nausea and a mild headache beginning the day after starting the fictional study medication DemoDrug 25 mg. No emergency care was needed.' },
    { id: 105, chunk_index: 1, page_number: 1, content: 'Severity and outcome: The event is described as mild. Symptoms resolved within 24 hours after the study medication was held. The investigator plans a follow-up call in seven days.' },
  ] },
}
export const demoExtractions: Record<string, Extraction> = Object.fromEntries(Object.entries(demoDetails).map(([id, document]) => [id, {
  document_id: id, filename: document.filename, items: document.chunks.map((chunk, index) => ({
    document_id: chunk.id, chunk_index: chunk.chunk_index, page_number: chunk.page_number, status: 'succeeded', error_type: null,
    result: { summary: index === 0 ? (id === 'demo-cardio' ? 'Follow-up record notes mild dizziness and blood pressure of 160/95 mmHg; chest pain and shortness of breath were denied.' : 'Participant reported mild nausea and headache after starting DemoDrug 25 mg.') : chunk.content,
      category: id === 'demo-cardio' ? 'Case Report' : 'Adverse Event',
      key_entities: index === 0 ? (id === 'demo-cardio' ? { symptom: 'Mild dizziness', blood_pressure: '160/95 mmHg', chest_pain: 'Denied', shortness_of_breath: 'Denied' } : { symptoms: ['Nausea', 'Mild headache'], medication: 'DemoDrug', dose: '25 mg' }) : {}, confidence: 0.94 },
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
