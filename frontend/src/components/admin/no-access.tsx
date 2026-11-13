export function NoAccess() {
  return (
    <div className="mx-auto max-w-md space-y-2 py-16 text-center">
      <h1 className="text-xl font-semibold">No access</h1>
      <p className="text-sm text-muted-foreground">Your account doesn't have a staff role that can use the admin console.</p>
      <a href="/" className="text-sm underline">Back to Styx</a>
    </div>
  );
}
