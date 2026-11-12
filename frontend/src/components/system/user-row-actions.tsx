import { AlertTriangle, KeyRound, MoreHorizontal, RefreshCw, Trash2, Unlock, UserRound, UsersRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { UserRow } from "@/components/system/users-filters";
import { useProfile } from "@/hooks/use-profile";

export type UserActions = {
  unlock: (u: UserRow) => void;
  resetPassword: (u: UserRow) => void;
  forceChange: (u: UserRow) => void;
  disable: (u: UserRow) => void;
  askDelete: (u: UserRow) => void;
  groups: (u: UserRow) => void;
  profiles: (u: UserRow) => void;
  matrix: (u: UserRow) => void;
};

/** Hover actions (Unlock, Reset password) plus the "⋯" menu for everything else. */
export function UserRowActions({ u, locked, a, self }: { u: UserRow; locked: boolean; a: UserActions; self?: boolean }) {
  const { isDisabled } = useProfile();  // enterprise (ADR-0053): no local passwords or sign-in cards
  const pw = !isDisabled("password_login");
  return (
    <>
      {locked && <Button variant="ghost" size="sm" className="text-primary" onClick={() => a.unlock(u)}>Unlock</Button>}
      {pw && <Button variant="ghost" size="sm" onClick={() => a.resetPassword(u)}>Reset password</Button>}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={`More actions for ${u.username}`}>
            <MoreHorizontal className="size-4" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {locked && <DropdownMenuItem onClick={() => a.unlock(u)}><Unlock className="mr-2 h-4 w-4" />Unlock</DropdownMenuItem>}
          <DropdownMenuItem onClick={() => a.groups(u)}><UsersRound className="mr-2 h-4 w-4" />Groups…</DropdownMenuItem>
          <DropdownMenuItem onClick={() => a.profiles(u)}><UserRound className="mr-2 h-4 w-4" />Profiles…</DropdownMenuItem>
          {pw && <DropdownMenuItem onClick={() => a.resetPassword(u)}><RefreshCw className="mr-2 h-4 w-4" />Reset password</DropdownMenuItem>}
          {pw && <DropdownMenuItem onClick={() => a.forceChange(u)}><AlertTriangle className="mr-2 h-4 w-4" />Force password change</DropdownMenuItem>}
          {u.has_matrix_card && !isDisabled("matrix_2fa") && (
            <DropdownMenuItem onClick={() => a.matrix(u)}><KeyRound className="mr-2 h-4 w-4" />Reset sign-in card</DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DropdownMenuItem disabled={self} onClick={() => a.disable(u)}><Trash2 className="mr-2 h-4 w-4" />Disable</DropdownMenuItem>
          <DropdownMenuItem disabled={self} className="text-destructive focus:text-destructive" onClick={() => a.askDelete(u)}>
            <Trash2 className="mr-2 h-4 w-4" />Delete permanently
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </>
  );
}
