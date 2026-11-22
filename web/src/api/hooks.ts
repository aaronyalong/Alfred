// One hook per API call. Pages that show work in progress poll until it's done: the worker
// runs in the background, and polling every 2 seconds is simple and enough at this scale.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "./client";
import type { CourseDetail, Given, SetDetail, SetIn } from "./client";

const POLL_MS = 2000;

const keys = {
  courses: ["courses"] as const,
  course: (id: string) => ["courses", id] as const,
  pages: (id: string) => ["documents", id, "pages"] as const,
  set: (id: string) => ["sets", id] as const,
};

export function isWorking(course: CourseDetail): boolean {
  return (
    course.documents.some((d) => d.status === "queued" || d.status === "parsing") ||
    course.sets.some((s) => s.status === "queued" || s.status === "generating")
  );
}

export function isPending(set: SetDetail): boolean {
  return set.status === "queued" || set.status === "generating";
}

export function useCourses() {
  return useQuery({
    queryKey: keys.courses,
    queryFn: async () => unwrap(await api.GET("/api/courses")),
  });
}

export function useCourse(id: string) {
  return useQuery({
    queryKey: keys.course(id),
    queryFn: async () =>
      unwrap(await api.GET("/api/courses/{course_id}", { params: { path: { course_id: id } } })),
    refetchInterval: (query) => (query.state.data && isWorking(query.state.data) ? POLL_MS : false),
  });
}

export function useCreateCourse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (name: string) => unwrap(await api.POST("/api/courses", { body: { name } })),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.courses }),
  });
}

export function useDeleteCourse() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/courses/{course_id}", { params: { path: { course_id: id } } })),
    onSuccess: (_, id) => {
      client.removeQueries({ queryKey: keys.course(id) });
      return client.invalidateQueries({ queryKey: keys.courses });
    },
  });
}

export function useUploadDocument(courseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) =>
      unwrap(
        await api.POST("/api/courses/{course_id}/documents", {
          params: { path: { course_id: courseId } },
          // The schema describes the upload as a string field; it is sent as a form file.
          body: { file: "" },
          bodySerializer: () => {
            const form = new FormData();
            form.append("file", file);
            return form;
          },
        }),
      ),
    onSettled: () => client.invalidateQueries({ queryKey: keys.course(courseId) }),
  });
}

export function useDocumentPages(documentId: string | null) {
  return useQuery({
    queryKey: keys.pages(documentId ?? ""),
    enabled: documentId !== null,
    staleTime: Infinity, // a parsed document never changes
    queryFn: async () =>
      unwrap(
        await api.GET("/api/documents/{document_id}/pages", {
          params: { path: { document_id: documentId ?? "" } },
        }),
      ),
  });
}

export function useCreateSet(courseId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: SetIn) =>
      unwrap(
        await api.POST("/api/courses/{course_id}/sets", {
          params: { path: { course_id: courseId } },
          body,
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.course(courseId) }),
  });
}

export function usePracticeSet(id: string) {
  return useQuery({
    queryKey: keys.set(id),
    queryFn: async () =>
      unwrap(await api.GET("/api/sets/{set_id}", { params: { path: { set_id: id } } })),
    refetchInterval: (query) => (query.state.data && isPending(query.state.data) ? POLL_MS : false),
  });
}

export function useSubmitAttempt(set: SetDetail) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (answers: Record<string, Given>) =>
      unwrap(
        await api.POST("/api/sets/{set_id}/attempts", {
          params: { path: { set_id: set.id } },
          body: {
            answers: Object.entries(answers).map(([question_id, answer]) => ({
              question_id,
              answer,
            })),
          },
        }),
      ),
    // The course page shows each set's latest score.
    onSuccess: () => client.invalidateQueries({ queryKey: keys.course(set.course_id) }),
  });
}

export function useFlagQuestion(setId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ questionId, flagged }: { questionId: string; flagged: boolean }) =>
      unwrap(
        await api.PUT("/api/questions/{question_id}/flag", {
          params: { path: { question_id: questionId } },
          body: { flagged },
        }),
      ),
    onSuccess: (_, { questionId, flagged }) =>
      client.setQueryData<SetDetail>(
        keys.set(setId),
        (set) =>
          set && {
            ...set,
            items: set.items.map((q) => (q.id === questionId ? { ...q, flagged } : q)),
          },
      ),
  });
}
