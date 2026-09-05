use crate::database::SELECT_ITEM_QUERY;
use serde::Serialize;
use sqlx::PgPool;
use std::{error::Error, fmt, future::Future, pin::Pin};

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct Item {
    pub id: i64,
    pub name: String,
    pub price: i32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ItemStoreError;

impl fmt::Display for ItemStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("item store query failed")
    }
}

impl Error for ItemStoreError {}

pub type FindItemFuture<'a> =
    Pin<Box<dyn Future<Output = Result<Option<Item>, ItemStoreError>> + Send + 'a>>;

pub trait ItemStore: Send + Sync {
    fn find_by_id(&self, id: i64) -> FindItemFuture<'_>;
}

#[derive(Clone)]
pub struct SqlxItemStore {
    pool: PgPool,
}

impl SqlxItemStore {
    #[must_use]
    pub fn new(pool: PgPool) -> Self {
        Self { pool }
    }
}

impl ItemStore for SqlxItemStore {
    fn find_by_id(&self, id: i64) -> FindItemFuture<'_> {
        Box::pin(async move {
            let row = sqlx::query_as::<_, (i64, String, i32)>(SELECT_ITEM_QUERY)
                .bind(id)
                .fetch_optional(&self.pool)
                .await
                .map_err(|_| ItemStoreError)?;

            Ok(row.map(|(id, name, price)| Item { id, name, price }))
        })
    }
}
