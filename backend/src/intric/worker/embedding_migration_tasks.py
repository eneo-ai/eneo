from uuid import UUID

import sqlalchemy as sa
from intric.database.tables.collections_table import CollectionsTable
from intric.database.tables.info_blob_chunk_table import InfoBlobChunks
from intric.info_blobs.info_blob import InfoBlobChunk
from intric.jobs.task_models import EmbeddingModelMigrationTask
from intric.main.container.container import Container
from intric.main.logging import get_logger

logger = get_logger(__name__)


async def embedding_model_migration_task(
    *,
    job_id: UUID,
    params: EmbeddingModelMigrationTask,
    container: Container,
):
    task_manager = container.task_manager(job_id=job_id)
    async with task_manager.set_status_on_exception():
        # Get required services
        session = container.session()
        info_blob_repo = container.info_blob_repo()
        info_blob_chunk_repo = container.info_blob_chunk_repo()
        embedding_model_repo = container.embedding_model_repo()
        
        # Get the new embedding model
        new_embedding_model = await embedding_model_repo.one(model_id=params.new_embedding_model_id)
        
        # Find all groups using the old embedding model
        stmt = sa.select(CollectionsTable).where(
            CollectionsTable.embedding_model_id == params.old_embedding_model_id
        )
        
        if params.group_limit:
            stmt = stmt.limit(params.group_limit)
            
        result = await session.execute(stmt)
        groups = result.scalars().all()
        
        logger.info(f"Starting migration of {len(groups)} groups from embedding model {params.old_embedding_model_id} to {params.new_embedding_model_id}")
        
        for group_index, group in enumerate(groups):
            logger.info(f"Processing group {group_index + 1}/{len(groups)}: {group.name} (ID: {group.id})")
            
            # Get all info_blobs for this group
            info_blobs = await info_blob_repo.get_by_group(group_id=group.id)
            logger.info(f"Found {len(info_blobs)} blobs in group {group.name}")
            
            # Process blobs in batches to manage memory
            blob_batch_size = 100
            for batch_start in range(0, len(info_blobs), blob_batch_size):
                batch_end = min(batch_start + blob_batch_size, len(info_blobs))
                blob_batch = info_blobs[batch_start:batch_end]
                
                logger.info(f"Processing blob batch {batch_start + 1}-{batch_end} of {len(info_blobs)}")
                
                for blob in blob_batch:
                    # Get existing chunks for this blob using the chunk repo's session
                    # Query chunks directly using the repo's session  
                    chunk_stmt = sa.select(InfoBlobChunks).where(
                        InfoBlobChunks.info_blob_id == blob.id
                    ).order_by(InfoBlobChunks.chunk_no)
                    
                    chunk_result = await info_blob_chunk_repo.session.execute(chunk_stmt)
                    existing_chunks = chunk_result.scalars().all()
                    
                    if not existing_chunks:
                        logger.warning(f"No chunks found for blob {blob.id}, skipping")
                        continue
                    
                    # Convert existing chunks to format needed for embedding generation
                    chunks_for_embedding = [
                        InfoBlobChunk(
                            text=chunk.text,
                            chunk_no=chunk.chunk_no,
                            info_blob_id=blob.id,
                        )
                        for chunk in existing_chunks
                    ]
                        
                    # Generate new embeddings using the new embedding model
                    embedding_service = container.create_embeddings_service()
                    new_chunk_embeddings = await embedding_service.get_embeddings(
                        model=new_embedding_model,
                        chunks=chunks_for_embedding
                    )
                    
                    # Delete existing chunks for this blob
                    await info_blob_chunk_repo.delete_by_info_blob(blob.id)
                    
                    # Add new chunks with new embeddings
                    await info_blob_chunk_repo.add(new_chunk_embeddings.chunks)
            
            # Update the group's embedding model after successfully processing all its blobs
            async with session.begin():
                update_stmt = (
                    sa.update(CollectionsTable)
                    .where(CollectionsTable.id == group.id)
                    .values(embedding_model_id=new_embedding_model.id)
                )
                await session.execute(update_stmt)
            
            logger.info(f"Updated group {group.name} to use new embedding model")
        
        logger.info(f"Migration completed successfully. Processed {len(groups)} groups.")
        task_manager.result_location = f"/api/v1/embedding-models/{params.new_embedding_model_id}/"

    return task_manager.successful()