import { create } from "zustand";
import type { JobStatus, AgentLog } from "./api";

interface AppState {
  // Current job
  jobId: string | null;
  jobStatus: JobStatus | null;
  isUploading: boolean;
  uploadProgress: number;
  logs: AgentLog[];
  wsConnected: boolean;

  // UI
  activeTab: "upload" | "processing" | "report";
  selectedCategory: string | null;
  reportSearchQuery: string;

  // Actions — accept either a value or an updater function (React-style)
  setJobId: (id: string | null) => void;
  setJobStatus: (status: JobStatus | null | ((prev: JobStatus | null) => JobStatus | null)) => void;
  setIsUploading: (v: boolean) => void;
  setUploadProgress: (v: number | ((prev: number) => number)) => void;
  addLog: (log: AgentLog) => void;
  setLogs: (logs: AgentLog[]) => void;
  setWsConnected: (v: boolean) => void;
  setActiveTab: (tab: "upload" | "processing" | "report") => void;
  setSelectedCategory: (cat: string | null) => void;
  setReportSearchQuery: (q: string) => void;
  reset: () => void;
}

const initialState = {
  jobId: null,
  jobStatus: null,
  isUploading: false,
  uploadProgress: 0,
  logs: [],
  wsConnected: false,
  activeTab: "upload" as const,
  selectedCategory: null,
  reportSearchQuery: "",
};

export const useAppStore = create<AppState>((set) => ({
  ...initialState,

  setJobId: (id) => set({ jobId: id }),
  setJobStatus: (status) =>
    set((s) => ({
      jobStatus: typeof status === "function" ? status(s.jobStatus) : status,
    })),
  setIsUploading: (v) => set({ isUploading: v }),
  setUploadProgress: (v) =>
    set((s) => ({
      uploadProgress: typeof v === "function" ? v(s.uploadProgress) : v,
    })),
  addLog: (log) => set((s) => ({ logs: [...s.logs, log] })),
  setLogs: (logs) => set({ logs }),
  setWsConnected: (v) => set({ wsConnected: v }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setSelectedCategory: (cat) => set({ selectedCategory: cat }),
  setReportSearchQuery: (q) => set({ reportSearchQuery: q }),
  reset: () => set(initialState),
}));
