from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Notification


async def notify(session: AsyncSession, user_id: str, title: str, body: str,
                 link: str | None = None) -> Notification:
    """Create an in-app notification for a user and commit it."""
    n = Notification(user_id=user_id, title=title, body=body, link=link)
    session.add(n)
    await session.commit()
    await session.refresh(n)
    return n
