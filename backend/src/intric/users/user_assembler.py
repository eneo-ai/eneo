from typing import Optional

from intric.main.models import CursorPaginatedResponse
from intric.users.user import UserInDB, UserSparse


class UserAssembler:
    def from_user_to_model(self, user: UserInDB) -> UserSparse:
        return UserSparse(**user.model_dump())

    def users_to_paginated_response(
        self,
        users: list[UserInDB],
        total_count: int,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        previous: bool = False,
    ):
        """
        Converts a list of UserInDB objects into a paginated response, handling pagination logic
        regarding next and previous cursors based on the given limit and direction.
        """

        if limit is None:
            users_public = [self.from_user_to_model(user) for user in users]
            return CursorPaginatedResponse(
                items=users_public, total_count=total_count, limit=limit
            )

        if not previous:
            if len(users) < limit:
                paginated_users = [self.from_user_to_model(user) for user in users]
                return CursorPaginatedResponse(
                    items=paginated_users,
                    total_count=total_count,
                    previous_cursor=cursor,
                    limit=limit,
                )

            next_cursor = users[-1].email
            paginated_users = [self.from_user_to_model(user=user) for user in users]
            return CursorPaginatedResponse(
                items=paginated_users,
                total_count=total_count,
                next_cursor=next_cursor,
                previous_cursor=cursor,
                limit=limit,
            )

        else:
            # if length of users > limit, more users still exist.
            if len(users) > limit:
                # last user on previous page
                previous = users[0]  # type: ignore[assignment]

                paginated_users = [
                    self.from_user_to_model(user)
                    # skip last user on previous page
                    for user in users[1:]
                ]
                return CursorPaginatedResponse(
                    items=paginated_users,
                    total_count=total_count,
                    next_cursor=cursor,
                    previous_cursor=previous.email,  # type: ignore[attr-defined]
                    limit=limit,
                )

            paginated_users = [self.from_user_to_model(user) for user in users]

            return CursorPaginatedResponse(
                items=paginated_users,
                total_count=total_count,
                next_cursor=cursor,
                limit=limit,
            )
