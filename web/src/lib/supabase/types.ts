export type Json = string | number | boolean | null | { [key: string]: Json } | Json[]

export type MemberRole = 'admin' | 'supervisor' | 'reviewer' | 'intake'
export type SubmittalStatus =
  | 'received' | 'triaging' | 'triaged' | 'in_review'
  | 'on_hold' | 'approved' | 'denied' | 'returned_incomplete'
export type ReviewOutcome = 'pending' | 'approved' | 'approved_with_conditions' | 'denied' | 'returned_incomplete'
export type CommentSeverity = 'correction_required' | 'clarification' | 'advisory'

export interface Database {
  public: {
    Tables: {
      agencies: {
        Row: {
          id: string
          slug: string
          name: string
          state: string
          city: string | null
          code_year: string
          rule_overrides: Json
          custom_rules: Json
          plan: string
          contract_start: string | null
          contract_end: string | null
          monthly_submittal_cap: number | null
          jurisdiction_key: string | null
          created_at: string
          updated_at: string
        }
        Insert: Omit<Database['public']['Tables']['agencies']['Row'], 'id' | 'created_at' | 'updated_at'>
        Update: Partial<Database['public']['Tables']['agencies']['Row']>
        Relationships: []
      }
      agency_members: {
        Row: {
          id: string
          agency_id: string
          user_id: string
          role: MemberRole
          display_name: string | null
          created_at: string
        }
        Insert: Omit<Database['public']['Tables']['agency_members']['Row'], 'id' | 'created_at'>
        Update: Partial<Database['public']['Tables']['agency_members']['Row']>
        Relationships: [
          {
            foreignKeyName: 'agency_members_agency_id_fkey'
            columns: ['agency_id']
            isOneToOne: false
            referencedRelation: 'agencies'
            referencedColumns: ['id']
          }
        ]
      }
      submittals: {
        Row: {
          id: string
          agency_id: string
          external_ref: string | null
          project_name: string | null
          project_address: string | null
          applicant_name: string | null
          applicant_email: string | null
          project_type: string | null
          scope_of_work: string | null
          status: SubmittalStatus
          scope: Json | null
          completeness_score: number | null
          triage_grade: string | null
          received_at: string
          due_at: string | null
          closed_at: string | null
          created_by: string | null
          created_at: string
          updated_at: string
        }
        Insert: {
          agency_id: string
          external_ref?: string | null
          project_name?: string | null
          project_address?: string | null
          applicant_name?: string | null
          applicant_email?: string | null
          project_type?: string | null
          scope_of_work?: string | null
          status?: SubmittalStatus
          scope?: Json | null
          completeness_score?: number | null
          triage_grade?: string | null
          due_at?: string | null
          closed_at?: string | null
          created_by?: string | null
        }
        Update: Partial<Database['public']['Tables']['submittals']['Row']>
        Relationships: [
          {
            foreignKeyName: 'submittals_agency_id_fkey'
            columns: ['agency_id']
            isOneToOne: false
            referencedRelation: 'agencies'
            referencedColumns: ['id']
          }
        ]
      }
      triage_runs: {
        Row: {
          id: string
          submittal_id: string
          agency_id: string
          report: Json
          findings_total: number
          findings_fail: number
          findings_warn: number
          findings_pass: number
          completeness_score: number | null
          started_at: string
          completed_at: string | null
          duration_ms: number | null
          llm_calls: number
          llm_cost_usd: number
          pipeline_version: string
        }
        Insert: Omit<Database['public']['Tables']['triage_runs']['Row'], 'id' | 'started_at'>
        Update: Partial<Database['public']['Tables']['triage_runs']['Row']>
        Relationships: [
          {
            foreignKeyName: 'triage_runs_submittal_id_fkey'
            columns: ['submittal_id']
            isOneToOne: false
            referencedRelation: 'submittals'
            referencedColumns: ['id']
          }
        ]
      }
      reviews: {
        Row: {
          id: string
          submittal_id: string
          agency_id: string
          reviewer_id: string
          cycle: number
          triage_run_id: string | null
          outcome: ReviewOutcome
          reviewer_notes: string | null
          started_at: string
          completed_at: string | null
          created_at: string
          updated_at: string
        }
        Insert: {
          submittal_id: string
          agency_id: string
          reviewer_id: string
          cycle?: number
          triage_run_id?: string | null
          outcome?: ReviewOutcome
          reviewer_notes?: string | null
          completed_at?: string | null
        }
        Update: Partial<Database['public']['Tables']['reviews']['Row']>
        Relationships: [
          {
            foreignKeyName: 'reviews_submittal_id_fkey'
            columns: ['submittal_id']
            isOneToOne: false
            referencedRelation: 'submittals'
            referencedColumns: ['id']
          }
        ]
      }
      review_comments: {
        Row: {
          id: string
          review_id: string
          submittal_id: string
          agency_id: string
          source_finding_id: string | null
          code_ref: string | null
          severity: CommentSeverity
          body: string
          origin: string
          ai_draft_id: string | null
          display_order: number
          created_by: string
          created_at: string
          updated_at: string
        }
        Insert: {
          review_id: string
          submittal_id: string
          agency_id: string
          source_finding_id?: string | null
          code_ref?: string | null
          severity?: CommentSeverity
          body: string
          origin?: string
          ai_draft_id?: string | null
          display_order?: number
          created_by: string
        }
        Update: Partial<Database['public']['Tables']['review_comments']['Row']>
        Relationships: [
          {
            foreignKeyName: 'review_comments_review_id_fkey'
            columns: ['review_id']
            isOneToOne: false
            referencedRelation: 'reviews'
            referencedColumns: ['id']
          }
        ]
      }
    }
    Views: Record<string, never>
    Functions: {
      user_agency_ids: { Args: Record<string, never>; Returns: string[] }
      user_role_in: { Args: { target_agency: string }; Returns: MemberRole }
    }
    Enums: {
      member_role: MemberRole
      submittal_status: SubmittalStatus
      review_outcome: ReviewOutcome
      comment_severity: CommentSeverity
    }
    CompositeTypes: Record<string, never>
  }
}

// Convenience row types
export type Agency = Database['public']['Tables']['agencies']['Row']
export type AgencyMember = Database['public']['Tables']['agency_members']['Row']
export type Submittal = Database['public']['Tables']['submittals']['Row']
export type TriageRun = Database['public']['Tables']['triage_runs']['Row']
export type Review = Database['public']['Tables']['reviews']['Row']
export type ReviewComment = Database['public']['Tables']['review_comments']['Row']

// Joined type returned by agency_members select with agencies(*)
export type AgencyMemberWithAgency = AgencyMember & {
  agencies: Agency
}

// Shared shape for "where on the PDF this fact came from". Mirrors
// EvidenceLocation in supabase/functions/_shared/extract.ts.
export interface EvidenceLocation {
  text: string
  page: number | null
  bbox: { x: number; y: number; w: number; h: number } | null
  sheet?: string | null
}

// Structured ambiguity emitted by the scope extractor when LLM and regex
// disagree (or the LLM flags an open question). Reviewers answer these
// via the AmbiguityCard. Legacy reports stored plain strings — the union
// type on TriageReport.scope.ambiguities keeps both renderable.
export interface Ambiguity {
  id: string
  field: string
  question: string
  evidence_location?: EvidenceLocation | null
  llm_value?: unknown
  regex_value?: unknown
  resolved_value?: unknown
  resolved_at?: string | null
  resolved_by?: string | null
}

export function isStructuredAmbiguity(a: unknown): a is Ambiguity {
  return typeof a === 'object' && a !== null && 'id' in a && 'field' in a
}

// Triage report shape (from the edge function output)
export interface TriageReport {
  scope: {
    occupancies: string[]
    construction_type: string | null
    area_sqft: number | null
    stories: number | null
    sprinklered: boolean | null
    ambiguities?: (string | Ambiguity)[]
    [key: string]: unknown
  }
  findings: TriageFinding[]
  completeness_score: number
  completeness_judgment: string
  ambiguities: (string | Ambiguity)[]
}

export interface TriageFinding {
  rule_id: string
  // NOTE: this field is historically misnamed — the backend Finding
  // type carries BOTH severity (critical|major|moderate|minor) and
  // status (pass|fail|warn|info). The two fields below preserve back-
  // compat while exposing the real shape.
  severity: 'fail' | 'warning' | 'info' | 'pass'
  // Real severity tier from the backend (mutated by Part 5 corpus gate
  // when it downgrades critical->major, etc.). Optional for back-compat
  // with old report JSON.
  severity_tier?: 'critical' | 'major' | 'moderate' | 'minor'
  status?: 'pass' | 'fail' | 'warn' | 'info'
  summary?: string
  code_ref: string
  description: string
  discipline?: string
  evidence?: string[]
  confidence: number
  draft_comment?: string
  // Set by the corpus citation pre-check (verifyCorpusCitations). When
  // true, the displayed citation either came from a low-similarity
  // corpus match or wasn't produced at all — reviewer must confirm.
  citation_unverified?: boolean
  // PDF coordinate provenance — drives the FindingCard annotation panel.
  evidence_location?: {
    text: string
    page: number | null
    bbox: { x: number; y: number; w: number; h: number } | null
    sheet?: string | null
  } | null
  citation?: {
    text: string
    source_url: string
    source_title: string
    source_domain?: string
    confidence: number
    notes?: string
  }
}
