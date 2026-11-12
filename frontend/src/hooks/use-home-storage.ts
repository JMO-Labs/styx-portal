import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";

export function useHomeStorage() {
  return useQuery({ queryKey: ["home-storage"], queryFn: api.getHomeStorage, staleTime: 60000 });
}
