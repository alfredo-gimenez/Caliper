/// @file Caliper.cpp
/// Caliper main class
///

#include "Caliper.h"

#include "AttributeStore.h"
#include "Context.h"
#include "ContextRecord.h"
#include "MemoryPool.h"
#include "Node.h"
#include "NodePtrQuery.h"
#include "SigsafeRWLock.h"
#include "Writer.h"

#include <signal.h>

#include <cstring>
#include <map>
#include <mutex>
#include <vector>
#include <utility>

using namespace cali;
using namespace std;


//
// --- static data initialization --------------------------------------------
//

const  std::size_t cali_node_pool_size = 100; // make this a config variable


//
// --- Caliper implementation
//

struct Caliper::CaliperImpl
{
    // --- static data

    static volatile sig_atomic_t s_siglock;
    static std::mutex            s_mutex;
    
    static unique_ptr<Caliper>   s_caliper;


    // --- data
    
    MemoryPool            m_mempool;

    mutable SigsafeRWLock m_nodelock;
    vector<Node*>         m_nodes;
    Node                  m_root;

    AttributeStore        m_attributes;
    Context               m_context;


    // --- constructor

    CaliperImpl()
        : m_mempool { 2 * 1024 * 1024 }, 
        m_root { CTX_INV_ID, CTX_INV_ID, 0, 0 } 
    {
        m_nodes.reserve(cali_node_pool_size);
    }

    ~CaliperImpl() {
        for ( auto &n : m_nodes )
            n->~Node();
    }


    // --- helpers

    Node* create_node(ctx_id_t attr, const void* data, size_t size) {
        const size_t align = 8;
        const size_t pad   = align - sizeof(Node)%align;

        char* ptr  = static_cast<char*>(m_mempool.allocate(sizeof(Node) + pad + size));

        m_nodelock.wlock();

        Node* node = new(ptr) 
            Node(m_nodes.size(), attr, memcpy(ptr+sizeof(Node)+pad, data, size), size);        

        m_nodes.push_back(node);
        m_nodelock.unlock();

        return node;
    }


    // --- Annotation interface

    ctx_err begin(ctx_id_t env, const Attribute& attr, const void* data, size_t size) {
        ctx_err ret = CTX_EINV;

        if (attr == Attribute::invalid)
            return CTX_EINV;

        ctx_id_t key = attr.id();

        if (attr.store_as_value() && size == sizeof(uint64_t)) {
            uint64_t val = 0;
            memcpy(&val, data, sizeof(uint64_t));
            ret = m_context.set(env, key, val, attr.is_global());
        } else {
            auto p = m_context.get(env, key);

            m_nodelock.rlock();

            Node* parent = p.first ? m_nodes[p.second] : &m_root;
            Node* node   = parent ? parent->first_child() : nullptr;

            while ( node && !node->equals(attr.id(), data, size) )
                node = node->next_sibling();

            m_nodelock.unlock();

            if (!node) {
                node = create_node(attr.id(), data, size);

                if (parent) {
                    m_nodelock.wlock();
                    parent->append(node);
                    m_nodelock.unlock();
                }
            }

            ret = m_context.set(env, key, node->id(), attr.is_global());
        }

        return ret;
    }

    ctx_err end(ctx_id_t env, const Attribute& attr) {
        if (attr == Attribute::invalid)
            return CTX_EINV;

        ctx_err  ret = CTX_EINV;
        ctx_id_t key = attr.id();

        if (attr.store_as_value())
            ret = m_context.unset(env, key);
        else {
            auto p = m_context.get(env, key);

            if (!p.first)
                return CTX_EINV;

            m_nodelock.rlock();

            Node* node = m_nodes[p.second];

            if (node->attribute() != attr.id()) {
                // For now, just continue before first node with this attribute
                while (node && node->attribute() != attr.id())
                    node = node->parent();

                if (!node)
                    return CTX_EINV;
            }

            node = node->parent();
            m_nodelock.unlock();

            if (node == &m_root)
                ret = m_context.unset(env, key);
            else if (node)
                ret = m_context.set(env, key, node->id());
        }

        return ret;
    }

    ctx_err set(ctx_id_t env, const Attribute& attr, const void* data, size_t size) {
        if (attr == Attribute::invalid)
            return CTX_EINV;

        ctx_err  ret = CTX_EINV;
        ctx_id_t key = attr.id();

        if (attr.store_as_value() && size == sizeof(uint64_t)) {
            uint64_t val = 0;
            memcpy(&val, data, sizeof(uint64_t));
            ret = m_context.set(env, key, val, attr.is_global());
        } else {
            auto p = m_context.get(env, key);

            Node* parent { nullptr };

            m_nodelock.rlock();

            if (p.first)
                parent = m_nodes[p.second]->parent();
            if (!parent)
                parent = &m_root;

            Node* node = parent->first_child();

            while ( node && !node->equals(attr.id(), data, size) )
                node = node->next_sibling();

            m_nodelock.unlock();

            if (!node) {
                node = create_node(attr.id(), data, size);

                if (parent) {
                    m_nodelock.wlock();
                    parent->append(node);
                    m_nodelock.unlock();
                }
            }

            ret = m_context.set(env, key, node->id(), attr.is_global());
        }

        return ret;
    }


    // --- Retrieval

    const Node* get(ctx_id_t id) const {
        if (id > m_nodes.size())
            return nullptr;

        const Node* ret = nullptr;

        m_nodelock.rlock();
        ret = m_nodes[id];
        m_nodelock.unlock();

        return ret;
    }


    // --- Serialization API

    void write_nodes(NodeWriter& w) {
        // Need locking?
        for (Node* node : m_nodes)
            if (node)
                w.write(NodePtrQuery(m_attributes.get(node->attribute()), node));
    }
};


// --- static member initialization

volatile sig_atomic_t Caliper::CaliperImpl::s_siglock = 1;
mutex                 Caliper::CaliperImpl::s_mutex;

unique_ptr<Caliper>   Caliper::CaliperImpl::s_caliper;

Caliper::QueryKey     Caliper::QueryKey::invalid { CTX_INV_ID, 0 };


//
// --- Caliper class definition
//

Caliper::Caliper()
    : mP(new CaliperImpl)
{ 
}

Caliper::~Caliper()
{
    mP.reset(nullptr);
}


// --- Context API

ctx_id_t 
Caliper::current_environment() const
{
    return 0;
}

ctx_id_t 
Caliper::clone_environment(ctx_id_t env)
{
    return mP->m_context.clone_environment(env);
}

std::size_t 
Caliper::context_size(ctx_id_t env) const
{
    return mP->m_context.context_size(env);
}

std::size_t 
Caliper::get_context(ctx_id_t env, uint64_t buf[], std::size_t len) const
{
    return mP->m_context.get_context(env, buf, len);
}


// --- Annotation interface

ctx_err 
Caliper::begin(ctx_id_t env, const Attribute& attr, const void* data, size_t size)
{
    return mP->begin(env, attr, data, size);
}

ctx_err 
Caliper::end(ctx_id_t env, const Attribute& attr)
{
    return mP->end(env, attr);
}

ctx_err 
Caliper::set(ctx_id_t env, const Attribute& attr, const void* data, size_t size)
{
    return mP->set(env, attr, data, size);
}


// --- Attribute API

Attribute
Caliper::get_attribute(ctx_id_t id) const
{
    return mP->m_attributes.get(id);
}

Attribute
Caliper::get_attribute(const std::string& name) const
{
    return mP->m_attributes.get(name);
}

Attribute 
Caliper::create_attribute(const std::string& name, ctx_attr_type type, int prop)
{
    return mP->m_attributes.create(name, type, prop);
}


// --- Caliper query API

std::vector< std::unique_ptr<Query> >
Caliper::unpack(const uint64_t buf[], size_t size) const
{
    return ContextRecord::unpack(
        [this](ctx_id_t id){ return mP->m_attributes.get(id); },
        [this](ctx_id_t id){ return mP->get(id); },
        buf, size);                                 
}


// --- Serialization API

void
Caliper::write_nodes(NodeWriter& w)
{
    mP->write_nodes(w);
}

void
Caliper::write_attributes(AttributeWriter& w)
{
    mP->m_attributes.write(w);
}


// --- Caliper singleton API

Caliper* Caliper::instance()
{
    if (CaliperImpl::s_siglock == 1) {
        lock_guard<mutex> lock(CaliperImpl::s_mutex);

        if (!CaliperImpl::s_caliper) {
            CaliperImpl::s_caliper.reset(new Caliper);
            CaliperImpl::s_siglock = 0;
        }
    }

    return CaliperImpl::s_caliper.get();
}

Caliper* Caliper::try_instance()
{
    return CaliperImpl::s_siglock == 0 ? CaliperImpl::s_caliper.get() : nullptr;
}