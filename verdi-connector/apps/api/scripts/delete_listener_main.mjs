import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

try {
  const acc = await prisma.technicalAccount.findFirst({ where: { sessionName: 'listener_main' } });
  if (!acc) {
    console.log('no listener_main account');
    process.exit(0);
  }

  const convs = await prisma.conversation.findMany({
    where: { technicalAccountId: acc.id },
    select: { id: true },
  });
  const ids = convs.map((x) => x.id);
  console.log('delete convs', ids.length);

  if (ids.length) {
    await prisma.message.deleteMany({ where: { conversationId: { in: ids } } });
    await prisma.outboxMessage.deleteMany({ where: { conversationId: { in: ids } } });
    await prisma.moderationCase.deleteMany({ where: { conversationId: { in: ids } } });
    await prisma.riskEvent.deleteMany({ where: { conversationId: { in: ids } } });
    await prisma.conversation.deleteMany({ where: { id: { in: ids } } });
  }

  await prisma.technicalAccount.delete({ where: { id: acc.id } });
  console.log('deleted listener_main');
} finally {
  await prisma.$disconnect();
}

