// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.
import 'dart:async';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pyble/data/draft_repository.dart';
import 'package:pyble/editor/draft_recovery.dart';
import 'package:pyble/editor/editor_document.dart';

class Store implements DraftRepository {
  Store({this.snapshot, this.generation = 0});
  DraftSnapshot? snapshot;
  int generation;
  final List<DraftSnapshot> writes = [];
  Completer<DraftRead>? heldLoad;
  Completer<void>? heldWrite;
  DraftStorageFailure? failure;
  int loads=0, clears=0, active=0, maxActive=0;
  @override Future<DraftRead> load() async { loads++; return heldLoad?.future ?? DraftRead(generation:generation,snapshot:snapshot); }
  @override Future<void> write(DraftSnapshot value,{required int expectedGeneration}) async {
    active++; if(active>maxActive) maxActive=active;
    try {
      await heldWrite?.future;
      if(failure!=null) throw DraftStorageException(failure!);
      if(generation!=expectedGeneration || value.generation<=generation) throw const DraftStorageException(DraftStorageFailure.conflict);
      writes.add(value); snapshot=value; generation=value.generation;
    } finally {active--;}
  }
  @override Future<int> clear({required int expectedGeneration}) async {
    if(failure!=null) throw DraftStorageException(failure!);
    if(generation!=expectedGeneration) throw const DraftStorageException(DraftStorageFailure.conflict);
    clears++; snapshot=null; return ++generation;
  }
  @override Future<void> close() async {}
}
DraftSnapshot saved()=>DraftSnapshot(name:'blink.py',content:'print(“exact”)\n',originPath:'/lib/blink.py',generation:17,checkpointTime:DateTime.utc(2026,10,31));
void main(){
  ProviderContainer container(Store store){
    final c=ProviderContainer(overrides:[draftRepositoryProvider.overrideWithValue(store)]);
    addTearDown(c.dispose); return c;
  }
  DraftRecoveryController recovery(ProviderContainer c)=>c.read(draftRecoveryProvider.notifier);
  EditorDocumentController editor(ProviderContainer c)=>c.read(editorDocumentProvider.notifier);
  test('existing harnesses have no implicit disk access',(){final c=ProviderContainer();addTearDown(c.dispose);expect(c.read(draftRecoveryProvider).status,DraftRecoveryStatus.disabled);});
  test('startup offers committed copy without hydrating or writing',()async{
    final s=Store(snapshot:saved(),generation:17),c=container(s);await recovery(c).start();
    expect(c.read(draftRecoveryProvider).status,DraftRecoveryStatus.decision);
    expect(c.read(draftRecoveryProvider).candidate?.content,saved().content);
    expect(c.read(editorDocumentProvider).content,isEmpty);expect(s.writes,isEmpty);expect(s.clears,0);
  });
  test('Restore is dirty, unbound and does not delete or rewrite copy',()async{
    final s=Store(snapshot:saved(),generation:17),c=container(s);await recovery(c).start();
    expect(recovery(c).restore(),isTrue);expect(c.read(editorDocumentProvider).content,saved().content);
    expect(c.read(editorDocumentProvider).dirty,isTrue);expect(c.read(editorDocumentProvider).boardPath,isNull);
    expect(c.read(editorRecoveredDraftProvider),isTrue);expect(s.snapshot,isNotNull);expect(s.writes,isEmpty);
    expect(c.read(draftRecoveryProvider).status,DraftRecoveryStatus.saved);
  });
  test('failed Discard preserves prompt and stored copy',()async{
    final s=Store(snapshot:saved(),generation:17),c=container(s);await recovery(c).start();s.failure=DraftStorageFailure.unavailable;
    expect(await recovery(c).discard(),isFalse);expect(c.read(draftRecoveryProvider).candidate,isNotNull);
    expect(c.read(draftRecoveryProvider).blocksStartup,isTrue);expect(s.snapshot,isNotNull);
  });
  test('Discard commits newer tombstone before clearing decision',()async{
    final s=Store(snapshot:saved(),generation:17),c=container(s);await recovery(c).start();
    expect(await recovery(c).discard(),isTrue);expect(s.generation,18);expect(s.snapshot,isNull);
    expect(c.read(draftRecoveryProvider).blocksStartup,isFalse);expect(c.read(editorDocumentProvider).content,isEmpty);
  });
  test('manual checkpoint acknowledges captured epoch, not later edits',()async{
    final s=Store(),c=container(s);await recovery(c).start();editor(c).setContent('first');s.heldWrite=Completer<void>();
    final write=recovery(c).saveRecoveryCopy();await Future<void>.delayed(Duration.zero);editor(c).setContent('newer');s.heldWrite!.complete();
    expect(await write,isTrue);expect(s.snapshot?.content,'first');expect(c.read(draftRecoveryProvider).status,DraftRecoveryStatus.pending);
  });
  testWidgets('idle edits checkpoint after 500ms and clean named empty file persists',(tester)async{
    final s=Store(),c=container(s);await recovery(c).start();editor(c).openFromBoard(path:'/empty.py',content:'');
    await tester.pump(const Duration(milliseconds:499));expect(s.writes,isEmpty);
    await tester.pump(const Duration(milliseconds:1));await tester.pump();expect(s.snapshot?.name,'empty.py');
    expect(s.snapshot?.content,isEmpty);expect(c.read(draftRecoveryProvider).status,DraftRecoveryStatus.saved);
  });
  testWidgets('continuous edits checkpoint within two seconds',(tester)async{
    final s=Store(),c=container(s);await recovery(c).start();
    for(int i=0;i<5;i++){editor(c).setContent('edit $i');await tester.pump(const Duration(milliseconds:400));}
    await tester.pump();expect(s.writes,isNotEmpty);expect(s.maxActive,1);
  });
  test('failed checkpoint retains live text and previous copy',()async{
    final s=Store(snapshot:saved(),generation:17),c=container(s);await recovery(c).start();recovery(c).restore();editor(c).setContent('newer');s.failure=DraftStorageFailure.tooLarge;
    expect(await recovery(c).saveRecoveryCopy(),isFalse);expect(s.snapshot?.content,saved().content);expect(c.read(editorDocumentProvider).content,'newer');
    expect(c.read(draftRecoveryProvider).status,DraftRecoveryStatus.failed);expect(c.read(draftRecoveryProvider).failure,DraftStorageFailure.tooLarge);
  });
  test('volatile continuation fences delayed hydration and protects old storage',()async{
    final s=Store()..heldLoad=Completer<DraftRead>();final c=container(s);final startup=recovery(c).start();recovery(c).continueWithoutRecovery();editor(c).setContent('live');
    s.heldLoad!.complete(DraftRead(generation:17,snapshot:saved()));await startup;expect(c.read(editorDocumentProvider).content,'live');
    expect(c.read(draftRecoveryProvider).status,DraftRecoveryStatus.volatile);expect(await recovery(c).saveRecoveryCopy(),isFalse);expect(s.writes,isEmpty);
  });
  testWidgets('ten second timeout and retry do not duplicate active load',(tester)async{
    final s=Store()..heldLoad=Completer<DraftRead>();final c=container(s);final startup=recovery(c).start();await tester.pump(const Duration(seconds:10));
    expect(c.read(draftRecoveryProvider).timedOut,isTrue);final retry=recovery(c).retry();expect(s.loads,1);recovery(c).continueWithoutRecovery();
    s.heldLoad!.complete(const DraftRead(generation:0));await startup;await retry;
  });
  test('volatile Retry offers choice without replacing current text',()async{
    final s=Store(snapshot:saved(),generation:17),c=container(s);recovery(c).continueWithoutRecovery();editor(c).setContent('live');await recovery(c).retry();
    expect(c.read(draftRecoveryProvider).candidate?.content,saved().content);expect(c.read(editorDocumentProvider).content,'live');expect(c.read(draftRecoveryProvider).status,DraftRecoveryStatus.decision);
  });
  test('replacement failure preserves current document and previous durable copy',()async{
    final s=Store(snapshot:saved(),generation:17),c=container(s);await recovery(c).start();recovery(c).restore();s.failure=DraftStorageFailure.unavailable;
    expect(await recovery(c).replaceDocument(const EditorDocument(name:'new.py',content:'new',dirty:true),expectedEpoch:c.read(editorDocumentEpochProvider)),isFalse);
    expect(c.read(editorDocumentProvider).content,saved().content);expect(s.snapshot?.content,saved().content);
  });
  test('replacement rejects stale edit-away/back epoch',()async{
    final s=Store(),c=container(s);await recovery(c).start();editor(c).setContent('first');final captured=c.read(editorDocumentEpochProvider);
    editor(c).setContent('other');editor(c).setContent('first');expect(await recovery(c).replaceDocument(const EditorDocument.untitled(),expectedEpoch:captured),isFalse);
    expect(c.read(editorDocumentProvider).content,'first');expect(s.clears,0);
  });
  test('replacement waits for active write and prevents queued resurrection',()async{
    final s=Store(),c=container(s);await recovery(c).start();editor(c).setContent('first');s.heldWrite=Completer<void>();
    final write=recovery(c).saveRecoveryCopy();await Future<void>.delayed(Duration.zero);editor(c).setContent('obsolete queued');
    final clear=recovery(c).replaceDocument(const EditorDocument.untitled(),expectedEpoch:c.read(editorDocumentEpochProvider));s.heldWrite!.complete();await write;
    expect(await clear,isTrue);expect(s.snapshot,isNull);expect(c.read(editorDocumentProvider).content,isEmpty);expect(s.maxActive,1);
  });
}
